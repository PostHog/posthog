from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

from django.db import transaction

from products.approvals.backend.actions.base import BaseAction
from products.approvals.backend.exceptions import ApplyFailed, PreconditionFailed
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE, flag_payload_codec
from products.feature_flags.backend.models.feature_flag import FeatureFlag

if TYPE_CHECKING:
    from products.approvals.backend.models import ChangeRequest


def _get_validated_change(request, view, *args, **kwargs) -> dict[str, Any]:
    """Resolve the change actually being saved.

    @approval_gate wraps both ``FeatureFlagSerializer.update(self, instance, validated_data)``
    (the validated change is ``args[1]``) and ``create(self, validated_data)`` (the validated
    change is ``args[0]`` — a dict, with no instance). The raw HTTP request body is NOT the
    source of truth: internal callers (experiment launch/pause/resume, ship_variant) drive
    ``serializer.update()`` from a POST whose body has no flag delta, yet the serializer's
    validated_data carries the real change. Read from validated_data first and only fall back to
    ``request.data`` when no validated change is available (e.g. direct detection calls in tests).
    """
    change: Optional[dict[str, Any]] = None

    if len(args) >= 2 and isinstance(args[1], dict):
        change = args[1]
    elif len(args) == 1 and isinstance(args[0], dict):
        # create(self, validated_data): the lone positional arg is the change itself.
        change = args[0]
    elif isinstance(kwargs.get("validated_data"), dict):
        change = kwargs["validated_data"]
    elif isinstance(getattr(view, "validated_data", None), dict):
        change = view.validated_data
    else:
        request_data = getattr(request, "data", None)
        change = request_data if isinstance(request_data, dict) else {}

    # FeatureFlagSerializer maps the `filters` field to `get_filters` in validated_data
    # (the rename back to `filters` happens inside update(), after the gate runs). Normalize
    # to the input field name `filters` so detection/intent — and the re-applied
    # full_request_data — read it regardless of the change's origin.
    if "get_filters" in change:
        normalized = {k: v for k, v in change.items() if k != "get_filters"}
        normalized.setdefault("filters", change["get_filters"])
        change = normalized

    return change


def _get_flag_instance(view, *args, **kwargs) -> Optional[FeatureFlag]:
    """Resolve the FeatureFlag being changed, or None on a create.

    @approval_gate wraps both ``update(self, instance, validated_data)`` (args[0] is the
    instance) and ``create(self, validated_data)`` (args[0] is the validated change dict, not
    a flag). BaseAction._get_instance returns args[0] indiscriminately, so on a create it hands
    back the dict — here we keep an instance only when it is an actual FeatureFlag.
    """
    if hasattr(view, "context") and "request" in view.context:
        instance = args[0] if args else None
        return instance if isinstance(instance, FeatureFlag) else None
    return view.get_object()


def _withhold_encrypted_payloads(
    change: dict[str, Any], flag: Optional[FeatureFlag]
) -> tuple[dict[str, Any], dict[str, str], Optional[bool]]:
    """Keep a secret flag payload out of the change a change request stores and replays.

    The gate runs before `encrypt_flag_payloads` in the serializer body, so `filters.payloads`
    still holds plaintext here. A change request stores that change in a JSONField and serves it
    to every member with approvals read scope, so the plaintext must not go in. Ciphertext cannot
    take its place either, because filters validation requires every payload string to parse as
    JSON and a Fernet token does not, which would fail the replay on apply.

    Return the change with each secret payload replaced by the sentinel that validation already
    accepts, the ciphertext to store beside it, and whether these payloads were secret when the
    change was captured — `None` when it carries none.

    That last value is stored beside the change rather than inside it. A flag's encryption
    setting can move between the request and the read, so the read path must not have to ask the
    flag; but writing the resolved value into the replayed change would also write it to the flag
    on apply, turning encryption off on a flag that was upgraded in the meantime.
    """
    payloads = (change.get("filters") or {}).get("payloads") or {}
    # A NULL column counts as not encrypted, which is how every other reader treats it.
    effective_has_encrypted = bool(
        change.get("has_encrypted_payloads", flag.has_encrypted_payloads if flag is not None else False)
    )
    if not effective_has_encrypted:
        return change, {}, (False if payloads else None)

    stored_payloads = ((flag.filters or {}).get("payloads") or {}) if flag is not None else {}
    # A sentinel means the client echoed back a payload it could not read, so there is nothing new
    # to withhold — but only where the flag actually holds ciphertext for that key. Anywhere else,
    # every key of a create included, the sentinel is an ordinary value, and banking it as if it
    # were ciphertext would leave a payload map that cannot be decrypted at all.
    secrets = {
        key: value
        for key, value in payloads.items()
        if isinstance(value, str) and (value != REDACTED_PAYLOAD_VALUE or key not in stored_payloads)
    }
    if not secrets:
        return change, {}, (True if payloads else None)

    codec = flag_payload_codec()
    encrypted = {key: codec.encrypt(value.encode("utf-8")).decode("utf-8") for key, value in secrets.items()}

    replayable = dict(change)
    filters = dict(replayable["filters"])
    filters["payloads"] = {**payloads, **dict.fromkeys(secrets, REDACTED_PAYLOAD_VALUE)}
    replayable["filters"] = filters
    # Resolved so `update()` takes its encrypted branch on replay, the same value it would have
    # resolved against the flag itself.
    replayable["has_encrypted_payloads"] = True
    return replayable, encrypted, True


def _flag_keeps_payloads_encrypted(change_request: "ChangeRequest") -> bool:
    """Ask the flag itself whether it keeps its payloads encrypted.

    Reached only for a stored change that holds a readable payload and says nothing either way,
    which a write from before the gate withheld one can do: the serializer resolves the field
    against the flag inside its own body, after the gate has captured the change.

    Soft-deleted flags are included, and a flag that cannot be resolved at all counts as
    encrypted. Deleting a flag must not turn a withheld payload back into a readable one, and
    redaction that weakens when the resource disappears fails in the wrong direction. A create
    carries no flag to ask and no stored payload to protect, so it counts as not encrypted.

    Only a change stored before the gate recorded its own answer reaches here.
    """
    flag_id = change_request.intent.get("flag_id") or change_request.resource_id
    if not flag_id:
        return False
    try:
        # nosemgrep: idor-lookup-without-team (project_id from the change request's own team)
        row = (
            FeatureFlag.objects_including_soft_deleted.filter(
                id=flag_id,
                team__project_id=change_request.team.project_id,
            )
            .values_list("id", "has_encrypted_payloads")
            .first()
        )
    except (ValueError, TypeError):
        return True
    if row is None:
        return True
    # The column is nullable and a NULL counts as not encrypted, as every other reader treats it.
    # Selecting the id alongside it is what tells a NULL apart from a missing row.
    return bool(row[1])


def _hides_payloads(
    container: dict[str, Any], payloads: dict[str, Any], flag_keeps_payloads_encrypted: Callable[[], bool]
) -> bool:
    """Decide whether one validated change's `filters.payloads` must be replaced by the sentinel.

    `has_encrypted_payloads` sits beside `filters`, so that sibling decides when it is there —
    including when it says the payloads are not secret, which is how a change that turns
    encryption off shows an approver the plaintext it will apply. Payloads that are already all
    sentinel need no decision, which keeps the flag unasked for every change this gate withholds.
    """
    if "has_encrypted_payloads" in container:
        return bool(container["has_encrypted_payloads"])
    if all(value == REDACTED_PAYLOAD_VALUE for value in payloads.values()):
        return False
    return flag_keeps_payloads_encrypted()


def _redact_payloads(value: Any, flag_keeps_payloads_encrypted: Callable[[], bool]) -> Any:
    """Replace every secret flag payload inside a stored change with the sentinel."""
    if isinstance(value, dict):
        redacted = {key: _redact_payloads(item, flag_keeps_payloads_encrypted) for key, item in value.items()}
        filters = redacted.get("filters")
        if isinstance(filters, dict):
            payloads = filters.get("payloads")
            if isinstance(payloads, dict) and _hides_payloads(value, payloads, flag_keeps_payloads_encrypted):
                redacted["filters"] = {**filters, "payloads": dict.fromkeys(payloads, REDACTED_PAYLOAD_VALUE)}
        return redacted
    if isinstance(value, list):
        return [_redact_payloads(item, flag_keeps_payloads_encrypted) for item in value]
    return value


def _redact_change_request_for_read(data: dict[str, Any], change_request: "ChangeRequest") -> dict[str, Any]:
    """Remove the withheld ciphertext and every secret flag payload from a served change request.

    A change stored before the gate withheld the payload carries neither the marker nor a
    sentinel, so the flag is asked in that case: once per change request, however many response
    fields need the answer. An ordinary payload stays visible, because anyone who can read the
    flag can read it.
    """
    recorded = change_request.intent.get("payloads_were_encrypted")
    resolved: Optional[bool] = None

    def flag_keeps_payloads_encrypted() -> bool:
        nonlocal resolved
        # The gate records its own answer for every change that carries payloads, so only a row
        # stored before it did has to ask a flag whose setting may have moved since.
        if recorded is not None:
            return bool(recorded)
        if resolved is None:
            resolved = _flag_keeps_payloads_encrypted(change_request)
        return resolved

    redacted_data = dict(data)
    for field in ("intent", "intent_display"):
        stored = redacted_data.get(field)
        if isinstance(stored, dict) and stored:
            # The withheld ciphertext is only ever written at the intent root, so dropping the key
            # there leaves a flag payload variant that happens to share the name untouched.
            redacted_data[field] = _redact_payloads(
                {key: item for key, item in stored.items() if key != "encrypted_payloads"},
                flag_keeps_payloads_encrypted,
            )
    return redacted_data


def _check_version_staleness(intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None) -> bool:
    """Check staleness by comparing stored version precondition against current instance version."""
    preconditions = intent_data.get("preconditions", {})
    stored_version = preconditions.get("version")

    instance = context.get("instance") if context else None
    if not instance:
        # A create-type request has no flag row yet (stored_version is None) — that's expected,
        # not staleness. An update/enable/disable request whose flag can no longer be resolved
        # (e.g. deleted) genuinely is stale.
        return stored_version is not None

    if stored_version is not None and instance.version != stored_version:
        return True

    return False


def _resolve_existing_flag(change_request) -> Optional[FeatureFlag]:
    """Find the flag a change request operates on, if it already exists.

    For an update CR that's the stored flag_id/resource_id. For a create CR there is no row yet,
    but once applied the flag exists keyed by its `key` — resolving it here keeps re-validation
    and re-apply idempotent (no spurious unique-key failure, no duplicate).
    """
    flag_id = change_request.intent.get("flag_id") or change_request.resource_id
    if flag_id:
        try:
            # nosemgrep: idor-lookup-without-team (project_id from the approved change request's own team)
            return FeatureFlag.objects.get(id=flag_id, team__project_id=change_request.team.project_id)
        except FeatureFlag.DoesNotExist:
            return None

    key = change_request.intent.get("full_request_data", {}).get("key")
    if key:
        # nosemgrep: idor-lookup-without-team (project_id from the approved change request's own team)
        return FeatureFlag.objects.filter(
            team__project_id=change_request.team.project_id, key=key, deleted=False
        ).first()

    return None


def _apply_create(validated_intent: dict[str, Any], context: Optional[dict[str, Any]]) -> FeatureFlag:
    """Create the flag described by an approved create change request.

    The CR has no resource row yet, so we drive FeatureFlagSerializer.create() from the stored
    payload. The apply path (apply_change_request) always threads team/team_id/project_id and a
    request context. Idempotency: if a live flag with this key already exists for the team (e.g.
    the CR is re-applied), return it instead of creating a duplicate.
    """
    if not context or not context.get("team_id"):
        raise ApplyFailed("Cannot apply feature flag create without team context")

    full_request_data = validated_intent["full_request_data"]
    key = full_request_data.get("key")
    team_id = context["team_id"]

    if key:
        # nosemgrep: idor-lookup-without-team (team_id resolved from the approved change request)
        existing = FeatureFlag.objects.filter(team_id=team_id, key=key, deleted=False).first()
        if existing:
            return existing

    serializer_context = {
        "team": context.get("team"),
        "team_id": team_id,
        "project_id": context.get("project_id"),
        # Already approved — keep the gate from re-firing on this serializer.
        "approval_apply": True,
        # A change request can hold its flag payload as ciphertext, separate from the
        # change being replayed. The serializer swaps it in after validation.
        "approval_encrypted_payloads": validated_intent.get("encrypted_payloads") or {},
    }
    if "request" in context:
        serializer_context["request"] = context["request"]

    serializer = FeatureFlagSerializer(data=full_request_data, context=serializer_context)

    if not serializer.is_valid():
        raise ApplyFailed(f"Serializer validation failed: {serializer.errors}")

    try:
        with transaction.atomic():
            return serializer.save()
    except Exception as e:
        raise ApplyFailed(f"Serializer save failed: {str(e)}")


class FeatureFlagActionBase(BaseAction):
    """Base class for feature flag state change actions."""

    resource_type = "feature_flag"
    endpoint_serializer_class = FeatureFlagSerializer
    intent_fields = ["active"]

    # Subclasses define the target state
    target_active_state: bool

    @classmethod
    def check_staleness(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> bool:
        return _check_version_staleness(intent_data, context)

    @classmethod
    def validate_intent(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        data_to_validate = intent_data.get("full_request_data", intent_data.get("gated_changes", {}))
        instance = context.get("instance") if context else None

        serializer = cls.endpoint_serializer_class(
            instance=instance,
            data=data_to_validate,
            partial=True,
            context=context or {},
        )

        is_valid = serializer.is_valid()
        return is_valid, None if is_valid else serializer.errors

    @classmethod
    def prepare_context(cls, change_request, base_context: dict) -> dict:
        context = base_context.copy()

        instance = _resolve_existing_flag(change_request)
        if instance is not None:
            context["instance"] = instance

        return context

    # Whether this action should fire when a brand-new flag is born in the target state.
    # Enabling a new flag is gated; a new disabled flag is harmless, so disable opts out.
    gate_on_create: bool = False

    @classmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        try:
            flag = _get_flag_instance(view, *args, **kwargs)
        except Exception:
            return False

        change = _get_validated_change(request, view, *args, **kwargs)

        if flag is None:
            # Create: gate only when the flag is born in the gated target state.
            # FeatureFlag.active defaults to True, so a create that omits `active`
            # still lands enabled — treat missing as the model default.
            desired_active = change.get("active", True)
            if not cls.gate_on_create or desired_active is not True or cls.target_active_state is not True:
                return False
        else:
            desired_active = change.get("active")
            current_active = flag.active
            if (
                desired_active is None
                or desired_active != cls.target_active_state
                or current_active == cls.target_active_state
            ):
                return False

        team = cls._get_team(view)
        if not team:
            return False

        return True

    @classmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        flag = _get_flag_instance(view, *args, **kwargs)
        change = _get_validated_change(request, view, *args, **kwargs)

        gated_changes = {}
        for field in cls.intent_fields:
            if field in change:
                gated_changes[field] = change[field]

        # A caller exempt from the serializer's opportunistic filter cleanup stays exempt when
        # the approved change replays, otherwise approving a lifecycle action strips the legacy
        # keys the direct call preserves.
        skip_cleanup = bool(getattr(request, "skip_opportunistic_filter_cleanup", False))

        replayable, encrypted_payloads, payloads_were_encrypted = _withhold_encrypted_payloads(change, flag)

        if flag is None:
            # Create: no row yet — baseline is a disabled flag and the payload is the create body.
            return {
                "flag_id": None,
                "flag_key": change.get("key"),
                "current_state": {"active": False},
                "gated_changes": gated_changes,
                "full_request_data": dict(replayable),
                "encrypted_payloads": encrypted_payloads,
                "payloads_were_encrypted": payloads_were_encrypted,
                "preconditions": {"version": None, "updated_at": None},
                "skip_opportunistic_filter_cleanup": skip_cleanup,
            }

        return {
            "flag_id": flag.id,
            "flag_key": flag.key,
            "current_state": {"active": flag.active},
            "gated_changes": gated_changes,
            "full_request_data": dict(replayable),
            "encrypted_payloads": encrypted_payloads,
            "payloads_were_encrypted": payloads_were_encrypted,
            "preconditions": {
                "version": flag.version,
                "updated_at": flag.updated_at.isoformat() if flag.updated_at else None,
            },
            "skip_opportunistic_filter_cleanup": skip_cleanup,
        }

    @classmethod
    def apply(cls, validated_intent: dict[str, Any], user, context: Optional[dict[str, Any]] = None) -> FeatureFlag:
        if not validated_intent.get("flag_id"):
            return _apply_create(validated_intent, context)

        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team (flag_id from validated change request intent, originally team-scoped)
            flag = FeatureFlag.objects.select_for_update().get(id=validated_intent["flag_id"])

            if flag.version != validated_intent["preconditions"]["version"]:
                raise PreconditionFailed(
                    f"Flag version mismatch: expected {validated_intent['preconditions']['version']}, "
                    f"got {flag.version}"
                )

            # Idempotency: already in target state
            if flag.active is cls.target_active_state:
                return flag

            serializer_context = {
                "team": context.get("team") if context else flag.team,
                "team_id": context.get("team_id") if context else flag.team_id,
                "project_id": context.get("project_id") if context else flag.team.project_id,
                # Already approved — keep the gate from re-firing on this serializer.
                "approval_apply": True,
                # A change request can hold its flag payload as ciphertext, separate from the
                # change being replayed. The serializer swaps it in after validation.
                "approval_encrypted_payloads": validated_intent.get("encrypted_payloads") or {},
            }

            if context and "request" in context:
                serializer_context["request"] = context["request"]

            serializer = FeatureFlagSerializer(
                instance=flag,
                data=validated_intent["full_request_data"],
                partial=True,
                context=serializer_context,
            )

            if not serializer.is_valid():
                raise ApplyFailed(f"Serializer validation failed: {serializer.errors}")

            try:
                flag = serializer.save(last_modified_by=user)
            except Exception as e:
                raise ApplyFailed(f"Serializer save failed: {str(e)}")

        return flag

    @classmethod
    def redact_for_read(cls, data: dict[str, Any], change_request: "ChangeRequest") -> dict[str, Any]:
        return _redact_change_request_for_read(data, change_request)

    @classmethod
    @abstractmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        """Subclasses provide action-specific display data."""
        pass


class EnableFeatureFlagAction(FeatureFlagActionBase):
    """Gate enabling feature flags in production."""

    key = "feature_flag.enable"
    version = 1
    description = "Enable a feature flag"
    target_active_state = True
    gate_on_create = True

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "description": f"Enable feature flag '{intent_data.get('flag_key', 'unknown')}'",
            "before": intent_data.get("current_state", {}),
            # The applied change, not just the gated subset. Archiving an enabled flag writes
            # `archived` alongside `active`, and only `active` is gated — showing `gated_changes`
            # asked an approver to consent to a disable and then archived the flag too.
            "after": intent_data.get("full_request_data") or intent_data.get("gated_changes", {}),
        }


class DisableFeatureFlagAction(FeatureFlagActionBase):
    """Gate disabling feature flags in production."""

    key = "feature_flag.disable"
    version = 1
    description = "Disable a feature flag"
    target_active_state = False

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "description": f"Disable feature flag '{intent_data.get('flag_key', 'unknown')}'",
            "before": intent_data.get("current_state", {}),
            # The applied change, not just the gated subset. Archiving an enabled flag writes
            # `archived` alongside `active`, and only `active` is gated — showing `gated_changes`
            # asked an approver to consent to a disable and then archived the flag too.
            "after": intent_data.get("full_request_data") or intent_data.get("gated_changes", {}),
        }


class UpdateFeatureFlagAction(BaseAction):
    """Gate feature flag field-level updates based on policy conditions."""

    key = "feature_flag.update"
    version = 1
    description = "Update feature flag fields"
    resource_type = "feature_flag"
    endpoint_serializer_class = FeatureFlagSerializer

    GATEABLE_FIELDS: dict[str, dict[str, str]] = {
        "rollout_percentage": {
            "type": "number",
            "display_name": "rollout percentage",
        }
    }

    # Each path is (keys_to_container..., field_name). The container can be a list of dicts
    # (e.g. groups) or a single dict (e.g. holdout). Both are handled by _extract_rollout_percentages.
    ROLLOUT_PERCENTAGE_PATHS = [
        ("groups", "rollout_percentage"),
        ("holdout", "exclusion_percentage"),
        ("multivariate", "variants", "rollout_percentage"),
    ]

    intent_fields = ["rollout_percentage"]

    @classmethod
    def check_staleness(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> bool:
        return _check_version_staleness(intent_data, context)

    @classmethod
    def _extract_rollout_percentages(cls, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract all rollout_percentage values from the filter structure.

        Locations checked are defined in ROLLOUT_PERCENTAGE_PATHS.
        Each path is a tuple of (keys_to_array..., field_name).

        Returns list of dicts with 'path' and 'value' for each found value.
        """
        results: list[dict[str, Any]] = []

        for path_spec in cls.ROLLOUT_PERCENTAGE_PATHS:
            array_path, field_name = path_spec[:-1], path_spec[-1]

            current: Any = filters
            for key in array_path:
                current = current.get(key) if isinstance(current, dict) else None
                if current is None:
                    break

            path_str = ".".join(array_path)

            if isinstance(current, dict) and field_name in current:
                results.append(
                    {
                        "path": f"{path_str}.{field_name}",
                        "value": current[field_name],
                    }
                )
            elif isinstance(current, list):
                for idx, item in enumerate(current):
                    if isinstance(item, dict) and field_name in item:
                        results.append(
                            {
                                "path": f"{path_str}[{idx}].{field_name}",
                                "value": item[field_name],
                            }
                        )

        return results

    @classmethod
    def _has_gateable_field_changes(cls, old_filters: dict[str, Any], new_filters: dict[str, Any]) -> bool:
        """Check if any gateable field has changed between old and new filters."""
        old_values = cls._extract_rollout_percentages(old_filters)
        new_values = cls._extract_rollout_percentages(new_filters)

        old_by_path = {v["path"]: v["value"] for v in old_values}
        new_by_path = {v["path"]: v["value"] for v in new_values}

        all_paths = set(old_by_path.keys()) | set(new_by_path.keys())

        for path in all_paths:
            old_val = old_by_path.get(path)
            new_val = new_by_path.get(path)
            if old_val != new_val:
                return True

        return False

    @classmethod
    def _get_triggered_paths(cls, old_filters: dict[str, Any], new_filters: dict[str, Any]) -> list[str]:
        """Get list of field paths that have changed."""
        old_values = cls._extract_rollout_percentages(old_filters)
        new_values = cls._extract_rollout_percentages(new_filters)

        old_by_path = {v["path"]: v["value"] for v in old_values}
        new_by_path = {v["path"]: v["value"] for v in new_values}

        all_paths = set(old_by_path.keys()) | set(new_by_path.keys())
        triggered = []

        for path in all_paths:
            old_val = old_by_path.get(path)
            new_val = new_by_path.get(path)
            if old_val != new_val:
                triggered.append(path)

        return triggered

    @classmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        try:
            flag = _get_flag_instance(view, *args, **kwargs)
        except Exception:
            return False

        change = _get_validated_change(request, view, *args, **kwargs)

        if flag is not None:
            desired_active = change.get("active")
            current_active = flag.active
            if desired_active is not None and desired_active != current_active:
                if "filters" not in change:
                    return False

        new_filters = change.get("filters")
        if not new_filters:
            return False

        # On a create there is no prior flag — compare the new rollout against an empty baseline,
        # so a flag born with any rollout trips an "any change / >0" policy.
        old_filters = (flag.filters or {}) if flag is not None else {}

        if not cls._has_gateable_field_changes(old_filters, new_filters):
            return False

        team = cls._get_team(view)
        if not team:
            return False

        return True

    @classmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        flag = _get_flag_instance(view, *args, **kwargs)
        change = _get_validated_change(request, view, *args, **kwargs)

        old_filters = (flag.filters or {}) if flag is not None else {}
        new_filters = change.get("filters", {})

        old_rollout_percentages = cls._extract_rollout_percentages(old_filters)
        new_rollout_percentages = cls._extract_rollout_percentages(new_filters)

        triggered_paths = cls._get_triggered_paths(old_filters, new_filters)

        replayable, encrypted_payloads, payloads_were_encrypted = _withhold_encrypted_payloads(change, flag)

        return {
            "flag_id": flag.id if flag is not None else None,
            "flag_key": flag.key if flag is not None else change.get("key"),
            "current_state": {
                "rollout_percentage": old_rollout_percentages,
            },
            "gated_changes": {
                "rollout_percentage": new_rollout_percentages,
            },
            "triggered_paths": triggered_paths,
            "full_request_data": dict(replayable),
            "encrypted_payloads": encrypted_payloads,
            "payloads_were_encrypted": payloads_were_encrypted,
            "preconditions": {
                "version": flag.version if flag is not None else None,
                "updated_at": (flag.updated_at.isoformat() if flag.updated_at else None) if flag is not None else None,
            },
        }

    @classmethod
    def validate_intent(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        data_to_validate = intent_data.get("full_request_data", {})
        instance = context.get("instance") if context else None

        serializer = cls.endpoint_serializer_class(
            instance=instance,
            data=data_to_validate,
            partial=True,
            context=context or {},
        )

        is_valid = serializer.is_valid()
        return is_valid, None if is_valid else serializer.errors

    @classmethod
    def prepare_context(cls, change_request, base_context: dict) -> dict:
        context = base_context.copy()

        instance = _resolve_existing_flag(change_request)
        if instance is not None:
            context["instance"] = instance

        return context

    @classmethod
    def apply(cls, validated_intent: dict[str, Any], user, context: Optional[dict[str, Any]] = None) -> FeatureFlag:
        if not validated_intent.get("flag_id"):
            return _apply_create(validated_intent, context)

        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team (flag_id from validated change request intent, originally team-scoped)
            flag = FeatureFlag.objects.select_for_update().get(id=validated_intent["flag_id"])

            if flag.version != validated_intent["preconditions"]["version"]:
                raise PreconditionFailed(
                    f"Flag version mismatch: expected {validated_intent['preconditions']['version']}, "
                    f"got {flag.version}"
                )

            serializer_context = {
                "team": context.get("team") if context else flag.team,
                "team_id": context.get("team_id") if context else flag.team_id,
                "project_id": context.get("project_id") if context else flag.team.project_id,
                # Already approved — keep the gate from re-firing on this serializer.
                "approval_apply": True,
                # A change request can hold its flag payload as ciphertext, separate from the
                # change being replayed. The serializer swaps it in after validation.
                "approval_encrypted_payloads": validated_intent.get("encrypted_payloads") or {},
            }

            if context and "request" in context:
                serializer_context["request"] = context["request"]

            serializer = FeatureFlagSerializer(
                instance=flag,
                data=validated_intent["full_request_data"],
                partial=True,
                context=serializer_context,
            )

            if not serializer.is_valid():
                raise ApplyFailed(f"Serializer validation failed: {serializer.errors}")

            try:
                flag = serializer.save(last_modified_by=user)
            except Exception as e:
                raise ApplyFailed(f"Serializer save failed: {str(e)}")

        return flag

    @classmethod
    def redact_for_read(cls, data: dict[str, Any], change_request: "ChangeRequest") -> dict[str, Any]:
        return _redact_change_request_for_read(data, change_request)

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        """Generate human-readable diff showing before/after for gated fields."""
        flag_key = intent_data.get("flag_key", "unknown")
        current_state = intent_data.get("current_state", {})
        gated_changes = intent_data.get("gated_changes", {})
        triggered_paths = intent_data.get("triggered_paths", [])

        changes_description = []
        before_values = current_state.get("rollout_percentage", [])
        after_values = gated_changes.get("rollout_percentage", [])

        before_by_path = {v["path"]: v["value"] for v in before_values}
        after_by_path = {v["path"]: v["value"] for v in after_values}

        for path in triggered_paths:
            before_val = before_by_path.get(path, "N/A")
            after_val = after_by_path.get(path, "N/A")
            field_display_name = cls.GATEABLE_FIELDS["rollout_percentage"]["display_name"]
            changes_description.append(f"{field_display_name} at {path}: {before_val}% -> {after_val}%")

        description = (
            f"Update {cls.GATEABLE_FIELDS['rollout_percentage']['display_name']} for feature flag '{flag_key}'"
        )
        if changes_description:
            description = f"{description}: {'; '.join(changes_description)}"

        return {
            "description": description,
            "before": current_state,
            "after": gated_changes,
            "triggered_paths": triggered_paths,
        }
