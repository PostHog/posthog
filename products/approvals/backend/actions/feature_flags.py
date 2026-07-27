from abc import abstractmethod
from typing import Any, Optional

from django.db import transaction

from products.approvals.backend.actions.base import BaseAction
from products.approvals.backend.exceptions import ApplyFailed, PreconditionFailed
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.models.feature_flag import FeatureFlag


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


def _check_version_staleness(intent_data: dict[str, Any], context: Optional[dict[str, Any]] = None) -> bool:
    """Check staleness by comparing stored version precondition against current instance version."""
    instance = context.get("instance") if context else None
    if not instance:
        return True

    preconditions = intent_data.get("preconditions", {})
    stored_version = preconditions.get("version")
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
            return FeatureFlag.objects.get(id=flag_id, team_id=change_request.team_id)
        except FeatureFlag.DoesNotExist:
            return None

    key = change_request.intent.get("full_request_data", {}).get("key")
    if key:
        # nosemgrep: idor-lookup-without-team (team_id from the approved change request)
        return FeatureFlag.objects.filter(team_id=change_request.team_id, key=key, deleted=False).first()

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

        if flag is None:
            # Create: no row yet — baseline is a disabled flag and the payload is the create body.
            return {
                "flag_id": None,
                "flag_key": change.get("key"),
                "current_state": {"active": False},
                "gated_changes": gated_changes,
                "full_request_data": dict(change),
                "preconditions": {"version": None, "updated_at": None},
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
            "after": intent_data.get("gated_changes", {}),
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
            "after": intent_data.get("gated_changes", {}),
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
            "full_request_data": dict(change),
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
