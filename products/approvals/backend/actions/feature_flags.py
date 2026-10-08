import json
from abc import abstractmethod
from typing import Any, Optional
from uuid import UUID

from django.db import transaction
from django.db.models import Model

from posthog.dataclasses import frozen

from products.approvals.backend.actions.base import BaseAction
from products.approvals.backend.exceptions import ApplyFailed, PreconditionFailed
from products.approvals.backend.ownership import OWNER_KIND_UNOWNED, owner_kind_changed
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.api.filters_schema import FEATURE_FLAG_OPERATOR_ALIASES
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.ownership import flag_owner_kind

# The API adds these keys to a property filter for display. The flag editor sends them back on
# every save, so a difference in them is not a change to who gets the flag.
DISPLAY_ONLY_PROPERTY_KEYS = frozenset({"label", "cohort_name", "group_key_names"})


def _to_wire_form(value: Any) -> Any:
    """Convert deserialized related objects in a validated change back to primary keys.

    A related field on FeatureFlagSerializer deserializes to model instances, so
    `analytics_dashboards` reaches the gate as a list of Dashboard objects. The intent must hold
    the wire form instead, because `intent` is a JSONField and because `validate_intent` and
    `apply` both feed `full_request_data` back through the serializer, which accepts a primary
    key and rejects an instance. A UUID primary key becomes a string, because JSON has no UUID
    type and PrimaryKeyRelatedField accepts the string form.
    """
    if isinstance(value, Model):
        return str(value.pk) if isinstance(value.pk, UUID) else value.pk
    if isinstance(value, list | tuple):
        return [_to_wire_form(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_wire_form(item) for key, item in value.items()}
    return value


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

    return {key: _to_wire_form(value) for key, value in change.items()}


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


def _flag_target_filter(intent_data: dict[str, Any]) -> dict[str, Any]:
    # An update of an existing flag can reach the gate as a POST, for example an experiment launch,
    # so it has no resource id either. Match it on the flag id, because the key can change while the
    # request waits. Only a create has no flag id, so a create matches other creates by key.
    if intent_data["flag_id"] is not None:
        return {"intent__flag_id": intent_data["flag_id"]}
    return {"intent__flag_id": None, "intent__flag_key": intent_data["flag_key"]}


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


def _derive_flag_owner_kind(team, resource_id: Optional[str], intent_data: dict[str, Any]) -> Optional[str]:
    """Classify the flag this change targets, for the ownership record on the change request.

    A create has no flag yet, so there is nothing to classify and nothing to re-verify; the same
    is true once a flag can no longer be resolved. Both return None rather than a wrong answer.
    """
    flag_id = intent_data.get("flag_id") or resource_id
    if not flag_id:
        return None

    try:
        # nosemgrep: idor-lookup-without-team (project_id comes from the change request's own team)
        flag = FeatureFlag.objects.get(id=flag_id, team__project_id=team.project_id)
    except (FeatureFlag.DoesNotExist, ValueError, TypeError):
        return None

    return flag_owner_kind(flag) or OWNER_KIND_UNOWNED


def _check_flag_staleness(intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None) -> bool:
    """Whether the flag moved out from under a pending change request.

    Two ways it can: the flag itself was edited, or a different product adopted it. The second
    matters on its own, because which policy applies is keyed on the owner, so an owner change
    puts the request in front of the wrong approvers.
    """
    if _check_version_staleness(intent_data, context):
        return True

    instance = context.get("instance") if context else None
    if instance is None:
        return False

    recorded = context.get("recorded_owner_kind") if context else None
    return owner_kind_changed(recorded, flag_owner_kind(instance) or OWNER_KIND_UNOWNED)


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


def _canonical_property(prop: Any) -> Any:
    """Normalize a property filter, so a stored filter and the same filter sent back compare equal.

    Stored filters can predate the serializer's normalization, and the API adds display keys on
    read. Both differences appear on a save that changes nothing about who gets the flag.
    """
    if not isinstance(prop, dict):
        return prop

    canonical = {
        key: value for key, value in prop.items() if key not in DISPLAY_ONLY_PROPERTY_KEYS and value is not None
    }

    operator = canonical.get("operator")
    if isinstance(operator, str):
        operator = FEATURE_FLAG_OPERATOR_ALIASES.get(operator, operator)
        canonical["operator"] = operator
    # A missing operator means an exact match.
    if operator == "exact":
        del canonical["operator"]

    if canonical.get("negation") is False:
        del canonical["negation"]

    key = canonical.get("key")
    if isinstance(key, int | float) and not isinstance(key, bool):
        canonical["key"] = str(key)

    return canonical


def _release_conditions(filters: dict[str, Any], bucketing_identifier: Optional[str]) -> list[dict[str, Any]]:
    """Return what decides who gets the flag, as path and value pairs.

    These are the settings the flag editor shows under "Release conditions": "match by", each
    condition set's properties and variant override, and early exit. `feature_enrollment` is not in
    that section, but flag evaluation checks it before any condition set, so it decides who gets the
    flag too. Rollout percentages are not here, because the rollout paths already compare them.

    The flag-level `aggregation_group_type_index` is not compared. The serializer derives it from the
    condition sets, and each set's own value below already carries it.
    """
    results: list[dict[str, Any]] = [
        # A null identifier buckets by distinct ID, the same as the default.
        {
            "path": "bucketing_identifier",
            "value": "device_id" if bucketing_identifier == "device_id" else "distinct_id",
        },
        {"path": "early_exit", "value": filters.get("early_exit") is True},
        {"path": "feature_enrollment", "value": filters.get("feature_enrollment") is True},
    ]

    groups = filters.get("groups")
    if not isinstance(groups, list):
        return results

    flag_aggregation = filters.get("aggregation_group_type_index")
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue

        # The properties of a condition set must all match, so their order does not matter.
        properties = sorted(
            (_canonical_property(prop) for prop in group.get("properties") or []),
            key=lambda prop: json.dumps(prop, sort_keys=True, default=str),
        )
        results.append(
            {
                "path": f"groups[{index}]",
                "value": {
                    "properties": properties,
                    # The serializer copies the flag-level value into a set that has no key of its own.
                    "aggregation_group_type_index": group.get("aggregation_group_type_index", flag_aggregation),
                    # An empty override serves the normal variant split, the same as no override.
                    "variant": group.get("variant") or None,
                },
            }
        )

    return results


def _precondition_version(request, flag: FeatureFlag) -> Optional[int]:
    """Return the flag version that the caller's change was made against.

    The flag editor sends back every field it loaded. A save from an editor opened before someone
    else changed the release conditions resends the old ones, and the gate reads that as a release
    condition change. Applying that request would revert the other edit, so the request records the
    caller's version and the apply refuses it as stale. A caller that sends no version gets the
    stored one.
    """
    request_data = getattr(request, "data", None)
    caller_version = request_data.get("version") if isinstance(request_data, dict) else None
    if (
        isinstance(caller_version, int)
        and not isinstance(caller_version, bool)
        and caller_version != (flag.version or 0)
    ):
        return caller_version
    return flag.version


@frozen
class _GatedValues:
    """The values of each gated field before and after a change, keyed by field name."""

    before: dict[str, list[dict[str, Any]]]
    after: dict[str, list[dict[str, Any]]]


class FeatureFlagActionBase(BaseAction):
    """Base class for feature flag state change actions."""

    resource_type = "feature_flag"
    endpoint_serializer_class = FeatureFlagSerializer
    intent_fields = ["active"]

    # Subclasses define the target state
    target_active_state: bool

    @classmethod
    def derive_owner_kind(
        cls,
        team,
        resource_id: Optional[str],
        intent_data: dict[str, Any],
    ) -> Optional[str]:
        return _derive_flag_owner_kind(team, resource_id, intent_data)

    @classmethod
    def get_target_filter(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return _flag_target_filter(intent_data)

    @classmethod
    def check_staleness(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> bool:
        return _check_flag_staleness(intent_data, context)

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

        context["recorded_owner_kind"] = change_request.owner_kind

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

        if flag is None:
            # Create: no row yet — baseline is a disabled flag and the payload is the create body.
            return {
                "flag_id": None,
                "flag_key": change.get("key"),
                "current_state": {"active": False},
                "gated_changes": gated_changes,
                "full_request_data": dict(change),
                "preconditions": {"version": None, "updated_at": None},
                "skip_opportunistic_filter_cleanup": skip_cleanup,
            }

        return {
            "flag_id": flag.id,
            "flag_key": flag.key,
            "current_state": {"active": flag.active},
            "gated_changes": gated_changes,
            "full_request_data": dict(change),
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
    """Gate changes to a feature flag's rollout and release conditions.

    A rollout change is gated on every flag. A release condition change is gated on a standalone
    flag only. Product code rewrites the release conditions of a flag its product owns, for example
    when an experiment freezes its exposure, and those writes cannot wait for an approval.
    """

    key = "feature_flag.update"
    version = 1
    description = "Change feature flag release conditions or rollout"
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

    # How the description names a release condition path other than a condition set.
    RELEASE_CONDITION_LABELS = {
        "bucketing_identifier": "match by",
        "early_exit": "early exit",
        "feature_enrollment": "early access enrollment",
    }

    @classmethod
    def derive_owner_kind(
        cls,
        team,
        resource_id: Optional[str],
        intent_data: dict[str, Any],
    ) -> Optional[str]:
        return _derive_flag_owner_kind(team, resource_id, intent_data)

    @classmethod
    def get_target_filter(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return _flag_target_filter(intent_data)

    @classmethod
    def check_staleness(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> bool:
        return _check_flag_staleness(intent_data, context)

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

    @staticmethod
    def _changed_paths(old_values: list[dict[str, Any]], new_values: list[dict[str, Any]]) -> list[str]:
        old_by_path = {v["path"]: v["value"] for v in old_values}
        new_by_path = {v["path"]: v["value"] for v in new_values}
        paths = [*new_by_path, *(path for path in old_by_path if path not in new_by_path)]
        return [path for path in paths if old_by_path.get(path) != new_by_path.get(path)]

    @classmethod
    def _gated_values(cls, flag: Optional[FeatureFlag], change: dict[str, Any]) -> _GatedValues:
        """Return the values of each gated field before and after the change.

        `release_conditions` is present only when the release conditions of a standalone flag
        changed. A create compares its rollout against an empty baseline, so a flag born with any
        rollout trips an "any change / >0" policy, and its release conditions are not compared:
        a new flag serves nobody until it is enabled, and `feature_flag.enable` gates that.
        """
        old_filters = (flag.filters or {}) if flag is not None else {}
        new_filters = change["filters"] if "filters" in change else old_filters

        before = {"rollout_percentage": cls._extract_rollout_percentages(old_filters)}
        after = {"rollout_percentage": cls._extract_rollout_percentages(new_filters)}
        if flag is None:
            return _GatedValues(before=before, after=after)

        old_release = _release_conditions(old_filters, flag.bucketing_identifier)
        new_release = _release_conditions(new_filters, change.get("bucketing_identifier", flag.bucketing_identifier))
        # The owner lookup runs queries, so it runs only after the cheap comparison found a change.
        if cls._changed_paths(old_release, new_release) and flag_owner_kind(flag) is None:
            before["release_conditions"] = old_release
            after["release_conditions"] = new_release

        return _GatedValues(before=before, after=after)

    @classmethod
    def _triggered_paths(cls, values: _GatedValues) -> list[str]:
        return [
            path for field in values.after for path in cls._changed_paths(values.before[field], values.after[field])
        ]

    @classmethod
    def detect(cls, request, view, *args, **kwargs) -> bool:
        try:
            flag = _get_flag_instance(view, *args, **kwargs)
        except Exception:
            return False

        change = _get_validated_change(request, view, *args, **kwargs)

        if not cls._triggered_paths(cls._gated_values(flag, change)):
            return False

        team = cls._get_team(view)
        if not team:
            return False

        return True

    @classmethod
    def extract_intent(cls, request, view, *args, **kwargs) -> dict[str, Any]:
        flag = _get_flag_instance(view, *args, **kwargs)
        change = _get_validated_change(request, view, *args, **kwargs)

        values = cls._gated_values(flag, change)

        # A caller exempt from the serializer's opportunistic filter cleanup stays exempt when
        # the approved change replays, the way the lifecycle base records it. Without this an
        # approved rollout writes the filters back without `super_groups` and `holdout_groups`.
        skip_cleanup = bool(getattr(request, "skip_opportunistic_filter_cleanup", False))

        return {
            "flag_id": flag.id if flag is not None else None,
            "flag_key": flag.key if flag is not None else change.get("key"),
            "current_state": values.before,
            "gated_changes": values.after,
            "triggered_paths": cls._triggered_paths(values),
            "full_request_data": dict(change),
            "preconditions": {
                "version": _precondition_version(request, flag) if flag is not None else None,
                "updated_at": (flag.updated_at.isoformat() if flag.updated_at else None) if flag is not None else None,
            },
            "skip_opportunistic_filter_cleanup": skip_cleanup,
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

        context["recorded_owner_kind"] = change_request.owner_kind

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
    def _release_condition_change(cls, path: str, before_paths: set[str], after_paths: set[str]) -> str:
        if not path.startswith("groups["):
            return cls.RELEASE_CONDITION_LABELS.get(path, path)

        label = f"condition set {int(path[len('groups[') : -1]) + 1}"
        if path not in before_paths:
            return f"{label} added"
        if path not in after_paths:
            return f"{label} removed"
        return label

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        """Generate human-readable diff showing before/after for gated fields."""
        flag_key = intent_data.get("flag_key", "unknown")
        current_state = intent_data.get("current_state", {})
        gated_changes = intent_data.get("gated_changes", {})
        triggered_paths = intent_data.get("triggered_paths", [])

        rollout_before = {v["path"]: v["value"] for v in current_state.get("rollout_percentage", [])}
        rollout_after = {v["path"]: v["value"] for v in gated_changes.get("rollout_percentage", [])}
        release_before = {v["path"] for v in current_state.get("release_conditions", [])}
        release_after = {v["path"] for v in gated_changes.get("release_conditions", [])}

        rollout_display_name = cls.GATEABLE_FIELDS["rollout_percentage"]["display_name"]
        release_changes: list[str] = []
        rollout_changes: list[str] = []
        for path in triggered_paths:
            if path in release_before or path in release_after:
                release_changes.append(cls._release_condition_change(path, release_before, release_after))
            else:
                before_val = rollout_before.get(path, "N/A")
                after_val = rollout_after.get(path, "N/A")
                rollout_changes.append(f"{rollout_display_name} at {path}: {before_val}% -> {after_val}%")

        changed_fields = [
            name
            for name, changes in (("release conditions", release_changes), (rollout_display_name, rollout_changes))
            if changes
        ] or [rollout_display_name]
        description = f"Update {' and '.join(changed_fields)} for feature flag '{flag_key}'"
        changes_description = [*release_changes, *rollout_changes]
        if changes_description:
            description = f"{description}: {'; '.join(changes_description)}"

        return {
            "description": description,
            "before": current_state,
            "after": gated_changes,
            "triggered_paths": triggered_paths,
        }
