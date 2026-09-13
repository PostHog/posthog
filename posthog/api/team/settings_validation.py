"""Validation helpers for project settings."""

import json
from typing import Any, cast

import re2
from pydantic import TypeAdapter
from pydantic_core import ValidationError as PydanticValidationError
from rest_framework import exceptions, serializers

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team, User
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project import Project
from posthog.types import AnyPropertyFilter

from . import team_config

test_account_filters_adapter = TypeAdapter(list[AnyPropertyFilter])


def _format_serializer_errors(serializer_errors: dict) -> str:
    """Formats DRF serializer errors into a human readable string."""
    error_messages: list[str] = []
    for field, field_errors in serializer_errors.items():
        if isinstance(field_errors, list):
            error_messages.extend(f"{field}: {error}" for error in field_errors)
        else:
            error_messages.append(f"{field}: {field_errors}")
    return ". ".join(error_messages)


_VALID_TRIGGER_PROPERTY_OPERATORS = {
    "exact",
    "is_not",
    "icontains",
    "not_icontains",
    "regex",
    "not_regex",
    "gt",
    "lt",
}

# Property types the SDK can evaluate client-side
_VALID_TRIGGER_PROPERTY_TYPES = {
    "event",
    "person",
}


def _validate_trigger_property_filters(properties: object, context: str) -> None:
    """Validate property filters on trigger conditions (events, URLs)."""
    if not isinstance(properties, list):
        raise exceptions.ValidationError(f"{context}: 'properties' must be an array.")

    for prop_idx, prop in enumerate(properties):
        if not isinstance(prop, dict):
            raise exceptions.ValidationError(f"{context}: property {prop_idx} must be a dictionary.")
        if "key" not in prop or not isinstance(prop["key"], str):
            raise exceptions.ValidationError(f"{context}: property {prop_idx} must have a string 'key' field.")
        if "type" not in prop or prop["type"] not in _VALID_TRIGGER_PROPERTY_TYPES:
            raise exceptions.ValidationError(
                f"{context}: property {prop_idx} must have a 'type' field with value: "
                f"{', '.join(sorted(_VALID_TRIGGER_PROPERTY_TYPES))}."
            )
        if "operator" in prop and prop["operator"] not in _VALID_TRIGGER_PROPERTY_OPERATORS:
            raise exceptions.ValidationError(
                f"{context}: property {prop_idx} has invalid operator '{prop['operator']}'. "
                f"Valid operators: {', '.join(sorted(_VALID_TRIGGER_PROPERTY_OPERATORS))}."
            )
        # All supported operators require a value (is_set/is_not_set are not supported)
        if "value" not in prop:
            raise exceptions.ValidationError(f"{context}: property {prop_idx} must have a 'value' field.")


def validate_test_account_filters(value: object) -> list[dict[str, object]]:
    try:
        test_account_filters_adapter.validate_python(value)
    except PydanticValidationError as error:
        raise exceptions.ValidationError(f"Must provide an array of valid property filters. {error}") from error

    return cast(list[dict[str, object]], value)


def _alias_backreferences(alias: str) -> list[int]:
    """Return the capture-group numbers a re2 replacement alias references (`\\1`..`\\9`, `\\0` for the
    whole match). A doubled `\\\\` is a literal backslash, not a back-reference, so it's skipped."""
    refs: list[int] = []
    i = 0
    while i < len(alias):
        if alias[i] == "\\" and i + 1 < len(alias):
            nxt = alias[i + 1]
            if nxt == "\\":
                i += 2
                continue
            # ASCII digits only. `str.isdigit()` also accepts characters like `²` and `٣`, which re2
            # substitutes as literal text, and `int()` rejects `²` outright.
            if "0" <= nxt <= "9":
                refs.append(int(nxt))
                i += 2
                continue
        i += 1
    return refs


def validate_path_cleaning_filters(value: object) -> object:
    """Validate path cleaning rules before they're saved. Each regex must compile under re2 (the
    engine ClickHouse `replaceRegexpAll` uses), and any `\\1`..`\\9` back-reference in the alias must
    point at a capture group the regex defines. This surfaces a mistake at save time instead of
    letting it fail the query later, when path cleaning runs."""
    if not value:
        return value
    if not isinstance(value, list):
        raise exceptions.ValidationError("Must provide a list of path cleaning rules.")

    for rule in value:
        if not isinstance(rule, dict):
            continue
        regex = rule.get("regex")
        alias = rule.get("alias")
        # A missing or empty regex still reaches ClickHouse, where `replaceRegexpAll` returns NULL for
        # a NULL pattern and an empty pattern matches at every position, interleaving the alias
        # through the whole path. Neither is recoverable at query time, so refuse the rule.
        if not isinstance(regex, str) or not regex:
            raise exceptions.ValidationError("A path cleaning rule needs a regex. Remove the rule or give it one.")
        try:
            compiled = re2.compile(regex)
        except re2.error as error:
            raise exceptions.ValidationError(f"Invalid path cleaning regex '{regex}': {error}") from error

        if not alias or not isinstance(alias, str):
            continue
        group_count = compiled.groups
        for ref in _alias_backreferences(alias):
            if ref > group_count:
                raise exceptions.ValidationError(
                    f"The alias '{alias}' references capture group \\{ref}, but its regex has "
                    f"{group_count} capture group(s). Add the group to the regex or fix the reference."
                )
    return value


def _get_organization_for_logs_settings_check(serializer: serializers.BaseSerializer) -> Organization | None:
    if serializer.instance is not None:
        team = (
            serializer.instance.passthrough_team
            if hasattr(serializer.instance, "passthrough_team")
            else serializer.instance
        )
        return team.organization

    get_organization = serializer.context.get("get_organization")
    if callable(get_organization):
        return cast(Organization | None, get_organization())

    return None


def validate_team_attrs(
    attrs: dict[str, Any], view: TeamAndOrgViewSetMixin, instance: Team | Project | None
) -> dict[str, Any]:
    if instance is not None:
        admin_fields_touched = team_config.TEAM_CONFIG_ADMIN_FIELDS_SET & attrs.keys()
        # `app_urls` (the toolbar / web analytics authorized URLs) carries a `field_access_control`
        # tying it to web analytics editor access. When access controls are enabled, defer to that
        # field-level check instead of the blanket project-admin gate, so a web analytics editor can
        # manage authorized URLs. Without access controls we keep the stricter admin-only behavior.
        if view.user_access_control.access_controls_supported:
            admin_fields_touched = admin_fields_touched - {"app_urls"}
        if admin_fields_touched:
            team_for_check = instance if isinstance(instance, Team) else instance.passthrough_team
            level = view.user_permissions.team(team_for_check).effective_membership_level
            if level is None or level < OrganizationMembership.Level.ADMIN:
                raise exceptions.PermissionDenied(
                    "Only project admins can modify these settings: " + ", ".join(sorted(admin_fields_touched))
                )
    else:
        # On create there's no team yet, so check the creator's org-level membership. Without this a
        # non-admin member (allowed to create projects via members_can_create_projects) could set
        # admin-only team fields like receive_org_level_activity_logs. `is_demo` is excluded — demo
        # project creation is intentionally open to members and gated separately. `name` is excluded
        # too — naming a project you're allowed to create is not the same as renaming an existing one.
        admin_fields_touched = (team_config.TEAM_CONFIG_ADMIN_FIELDS_SET - {"is_demo", "name"}) & attrs.keys()
        if admin_fields_touched:
            membership = OrganizationMembership.objects.filter(
                user=cast(User, view.request.user), organization_id=view.organization_id
            ).first()
            member_level = membership.level if membership else None
            if member_level is None or member_level < OrganizationMembership.Level.ADMIN:
                raise exceptions.PermissionDenied(
                    "Only organization admins can set these settings on project creation: "
                    + ", ".join(sorted(admin_fields_touched))
                )

    if "primary_dashboard" in attrs:
        if not instance:
            raise exceptions.ValidationError(
                {"primary_dashboard": "Primary dashboard cannot be set on project creation."}
            )
        if attrs["primary_dashboard"] and attrs["primary_dashboard"].team_id != instance.id:
            raise exceptions.ValidationError({"primary_dashboard": "Dashboard does not belong to this team."})

    if "autocapture_exceptions_errors_to_ignore" in attrs:
        if not isinstance(attrs["autocapture_exceptions_errors_to_ignore"], list):
            raise exceptions.ValidationError("Must provide a list for field: autocapture_exceptions_errors_to_ignore.")
        for error in attrs["autocapture_exceptions_errors_to_ignore"]:
            if not isinstance(error, str):
                raise exceptions.ValidationError(
                    "Must provide a list of strings to field: autocapture_exceptions_errors_to_ignore."
                )

        if len(json.dumps(attrs["autocapture_exceptions_errors_to_ignore"])) > 300:
            raise exceptions.ValidationError(
                "Field autocapture_exceptions_errors_to_ignore must be less than 300 characters. Complex config should be provided in posthog-js initialization."
            )
    return attrs
