from collections.abc import Sequence
from datetime import datetime, time
from typing import Any, cast
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.access_control.backend.facade.api import list_user_role_ids, list_user_roles
from products.access_control.backend.facade.contracts import UserRole
from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import AccountPropertyPinKind, TaskDigestCadence
from products.customer_analytics.backend.logic.account_property_pins import (
    MAX_PINNED_PROPERTIES,
    validate_pinned_properties,
)
from products.customer_analytics.backend.models import TeamCustomerAnalyticsConfig, UserCustomerAnalyticsConfig

PINNED_PROPERTIES_KEY = "pinned_properties"
PINNED_PROPERTIES_OVERRIDE_KEY = "pinned_properties_override"
FOLLOWED_DEFAULT_KEY = "followed_default_pinned_properties"
TASK_DIGEST_KEY = "task_digest"
DEFAULT_TASK_DIGEST = contracts.TaskDigestPreferences()

ACCOUNT_DETAIL_TABS_KEY = "account_detail_tabs"
ACCOUNT_DETAIL_SYSTEM_TAB_IDS = {
    "system:notes",
    "system:context",
    "system:automations",
    "system:tasks",
    "system:users",
    "system:relationships",
    "system:feature_requests",
    "system:usage",
    "system:spend",
    "system:opportunities",
    "system:conversations",
    "system:meetings",
}
MAX_ACCOUNT_DETAIL_TAB_IDS = 100


@transaction.atomic
def get_or_create_config(*, team_id: int, user_id: int) -> UserCustomerAnalyticsConfig:
    # Resolve an environment (child team) id to its root team once. `for_team` canonicalizes its
    # filter but not the create kwargs, so a raw id makes the lookup never match, and the unique
    # constraint then rejects every call after the first.
    canonical_team_id = resolve_effective_team_id(team_id)
    config, _ = UserCustomerAnalyticsConfig.objects.for_team(canonical_team_id, canonical=True).get_or_create(
        team_id=canonical_team_id,
        user_id=user_id,
        defaults={"properties": {}},
    )
    config = (
        UserCustomerAnalyticsConfig.objects.for_team(canonical_team_id, canonical=True)
        .select_for_update()
        .get(pk=config.pk)
    )
    if PINNED_PROPERTIES_KEY in config.properties:
        return config

    if not config.pinned_custom_property_definition_ids:
        return config

    legacy_references = [
        {"kind": AccountPropertyPinKind.CUSTOM_PROPERTY.value, "id": str(definition_id)}
        for definition_id in config.pinned_custom_property_definition_ids
    ]
    config.properties = {**config.properties, PINNED_PROPERTIES_KEY: legacy_references}
    config.save(update_fields=["properties", "updated_at"])
    return config


@transaction.atomic
def update_pinned_properties(
    *, team_id: int, user_id: int, references: Sequence[tuple[AccountPropertyPinKind, str]]
) -> UserCustomerAnalyticsConfig:
    validated_references = validate_pinned_properties(team_id=team_id, references=references)
    config = get_or_create_config(team_id=team_id, user_id=user_id)
    config.properties = {
        **config.properties,
        PINNED_PROPERTIES_KEY: [
            {"kind": kind.value, "id": reference_id} for kind, reference_id in validated_references
        ],
        PINNED_PROPERTIES_OVERRIDE_KEY: True,
    }
    config.properties.pop(FOLLOWED_DEFAULT_KEY, None)
    config.pinned_custom_property_definition_ids = [
        UUID(reference_id)
        for kind, reference_id in validated_references
        if kind == AccountPropertyPinKind.CUSTOM_PROPERTY
    ]
    config.save(update_fields=["properties", "pinned_custom_property_definition_ids", "updated_at"])
    return config


@transaction.atomic
def follow_default_pinned_properties(
    *, team_id: int, user_id: int, kind: contracts.DefaultPinnedAccountPropertiesSourceKindValue, role_id: UUID | None
) -> UserCustomerAnalyticsConfig:
    config = get_or_create_config(team_id=team_id, user_id=user_id)
    followed: dict[str, str] = {"kind": kind}
    if kind == "role":
        organization_id = (
            TeamCustomerAnalyticsConfig.objects.filter(team_id=config.team_id)
            .values_list("team__organization_id", flat=True)
            .first()
        )
        if (
            role_id is None
            or organization_id is None
            or role_id not in list_user_role_ids(user_id=user_id, organization_id=organization_id)
        ):
            raise contracts.InvalidPinnedAccountProperties(
                ["You can only follow the defaults of a role you belong to."]
            )
        followed["role_id"] = str(role_id)
    # Clearing the personal list means that if the followed role later disappears, the user falls
    # back to the automatic defaults rather than to pins they replaced.
    config.properties = {
        **{
            key: value
            for key, value in config.properties.items()
            if key not in (PINNED_PROPERTIES_KEY, PINNED_PROPERTIES_OVERRIDE_KEY)
        },
        FOLLOWED_DEFAULT_KEY: followed,
    }
    config.pinned_custom_property_definition_ids = []
    config.save(update_fields=["properties", "pinned_custom_property_definition_ids", "updated_at"])
    return config


@frozen
class ResolvedPinnedProperties:
    pinned_properties: list[contracts.PinnedAccountProperty]
    source: contracts.PinnedAccountPropertiesSource
    available_defaults: list[contracts.AvailableDefaultPinnedAccountProperties]


@frozen
class _MergedRoleDefaults:
    pinned_properties: list[contracts.PinnedAccountProperty]
    contributing_roles: list[contracts.PinnedAccountPropertiesRole]


def _to_pinned_properties(raw_references: Any) -> list[contracts.PinnedAccountProperty]:
    if not isinstance(raw_references, list):
        return []
    return [
        contracts.PinnedAccountProperty(
            kind=cast(contracts.PinnedAccountPropertyKind, reference["kind"]),
            id=str(reference["id"]),
        )
        for reference in raw_references
    ]


def _merge_role_default_pinned_properties(
    *, role_defaults: list[dict[str, Any]], user_roles: Sequence[UserRole]
) -> _MergedRoleDefaults:
    references_by_role_id = {entry["role_id"]: entry["pinned_properties"] for entry in role_defaults}
    merged: dict[tuple[str, str], contracts.PinnedAccountProperty] = {}
    contributing_roles: list[contracts.PinnedAccountPropertiesRole] = []
    for role in user_roles:
        role_added = False
        for reference in references_by_role_id.get(str(role.id), []):
            key = (reference["kind"], str(reference["id"]))
            if key not in merged:
                if len(merged) >= MAX_PINNED_PROPERTIES:
                    break
                merged[key] = contracts.PinnedAccountProperty(
                    kind=cast(contracts.PinnedAccountPropertyKind, reference["kind"]),
                    id=str(reference["id"]),
                )
                role_added = True
        if role_added:
            contributing_roles.append(contracts.PinnedAccountPropertiesRole(id=role.id, name=role.name))
    return _MergedRoleDefaults(
        pinned_properties=list(merged.values()),
        contributing_roles=contributing_roles,
    )


def _build_available_defaults(
    *,
    project_defaults: list[contracts.PinnedAccountProperty],
    role_defaults: list[dict[str, Any]],
    user_roles: Sequence[UserRole],
) -> list[contracts.AvailableDefaultPinnedAccountProperties]:
    references_by_role_id = {entry["role_id"]: entry["pinned_properties"] for entry in role_defaults}
    available: list[contracts.AvailableDefaultPinnedAccountProperties] = [
        contracts.AvailableDefaultPinnedAccountProperties(
            source=contracts.DefaultPinnedAccountPropertiesSource(kind="project", role=None),
            pinned_properties=project_defaults,
        )
    ]
    for role in user_roles:
        pins = _to_pinned_properties(references_by_role_id.get(str(role.id)))
        if pins:
            available.append(
                contracts.AvailableDefaultPinnedAccountProperties(
                    source=contracts.DefaultPinnedAccountPropertiesSource(
                        kind="role",
                        role=contracts.PinnedAccountPropertiesRole(id=role.id, name=role.name),
                    ),
                    pinned_properties=pins,
                )
            )
    return available


def _resolve_followed_default(
    followed: Any, available_defaults: list[contracts.AvailableDefaultPinnedAccountProperties]
) -> contracts.AvailableDefaultPinnedAccountProperties | None:
    if not isinstance(followed, dict):
        return None
    for available in available_defaults:
        if available.source.kind != followed.get("kind"):
            continue
        if available.source.role is None or str(available.source.role.id) == followed.get("role_id"):
            return available
    return None


def read_pinned_properties(config: UserCustomerAnalyticsConfig) -> ResolvedPinnedProperties:
    team_config = (
        TeamCustomerAnalyticsConfig.objects.filter(team_id=config.team_id)
        .values("default_pinned_properties", "role_default_pinned_properties", "team__organization_id")
        .first()
    )
    project_defaults = _to_pinned_properties(team_config["default_pinned_properties"]) if team_config else []
    role_defaults: list[dict[str, Any]] = (
        team_config["role_default_pinned_properties"]
        if team_config and isinstance(team_config["role_default_pinned_properties"], list)
        else []
    )
    user_roles = (
        list_user_roles(user_id=config.user_id, organization_id=team_config["team__organization_id"])
        if team_config is not None and role_defaults
        else []
    )
    available_defaults = _build_available_defaults(
        project_defaults=project_defaults,
        role_defaults=role_defaults,
        user_roles=user_roles,
    )

    followed = _resolve_followed_default(config.properties.get(FOLLOWED_DEFAULT_KEY), available_defaults)
    if followed is not None:
        return ResolvedPinnedProperties(
            pinned_properties=followed.pinned_properties,
            source=contracts.PinnedAccountPropertiesSource(
                kind=followed.source.kind,
                roles=[followed.source.role] if followed.source.role else [],
            ),
            available_defaults=available_defaults,
        )

    stored = config.properties.get(PINNED_PROPERTIES_KEY)
    if isinstance(stored, list) and (
        stored
        or config.properties.get(PINNED_PROPERTIES_OVERRIDE_KEY) is True
        or config.pinned_custom_property_definition_ids
    ):
        return ResolvedPinnedProperties(
            pinned_properties=_to_pinned_properties(stored),
            source=contracts.PinnedAccountPropertiesSource(kind="personal", roles=[]),
            available_defaults=available_defaults,
        )

    merged_role_defaults = _merge_role_default_pinned_properties(
        role_defaults=role_defaults,
        user_roles=user_roles,
    )
    if merged_role_defaults.pinned_properties:
        return ResolvedPinnedProperties(
            pinned_properties=merged_role_defaults.pinned_properties,
            source=contracts.PinnedAccountPropertiesSource(
                kind="role",
                roles=merged_role_defaults.contributing_roles,
            ),
            available_defaults=available_defaults,
        )

    return ResolvedPinnedProperties(
        pinned_properties=project_defaults,
        source=contracts.PinnedAccountPropertiesSource(kind="project", roles=[]),
        available_defaults=available_defaults,
    )


def read_task_digest(config: UserCustomerAnalyticsConfig) -> contracts.TaskDigestPreferences:
    """Read the digest preferences, filling in a disabled default for anything the row does not
    hold. A row written before this key existed, or holding only some of the three values, still
    reads as a complete set."""
    stored = config.properties.get(TASK_DIGEST_KEY)
    if not isinstance(stored, dict):
        stored = {}
    cadence = stored.get("cadence")
    return contracts.TaskDigestPreferences(
        enabled=stored.get("enabled") is True,
        send_time=_read_send_time(stored),
        cadence=cadence if cadence in TaskDigestCadence.values else DEFAULT_TASK_DIGEST.cadence,
    )


@transaction.atomic
def update_task_digest(
    *,
    team_id: int,
    user_id: int,
    enabled: bool | None = None,
    send_time: time | None = None,
    cadence: TaskDigestCadence | None = None,
) -> UserCustomerAnalyticsConfig:
    """Replace the values the caller passed and keep the rest of the digest preferences."""
    config = get_or_create_config(team_id=team_id, user_id=user_id)
    current = read_task_digest(config)
    config.properties = {
        **config.properties,
        TASK_DIGEST_KEY: {
            "enabled": current.enabled if enabled is None else enabled,
            "send_time": current.send_time
            if send_time is None
            else send_time.strftime(contracts.TASK_DIGEST_SEND_TIME_FORMAT),
            "cadence": current.cadence if cadence is None else cadence.value,
        },
    }
    config.save(update_fields=["properties", "updated_at"])
    return config


def read_account_detail_tabs(config: UserCustomerAnalyticsConfig) -> contracts.AccountDetailTabsConfig:
    stored = config.properties.get(ACCOUNT_DETAIL_TABS_KEY)
    if not isinstance(stored, dict):
        return contracts.AccountDetailTabsConfig()

    ordered_tab_ids = _read_tab_ids(stored.get("ordered_tab_ids"))
    hidden_tab_ids = _read_tab_ids(stored.get("hidden_tab_ids"))
    default_tab_id = stored.get("default_tab_id")
    return contracts.AccountDetailTabsConfig(
        ordered_tab_ids=ordered_tab_ids,
        hidden_tab_ids=hidden_tab_ids,
        default_tab_id=default_tab_id if isinstance(default_tab_id, str) and _is_tab_id(default_tab_id) else None,
    )


@transaction.atomic
def update_account_detail_tabs(
    *,
    team_id: int,
    user_id: int,
    ordered_tab_ids: list[str],
    hidden_tab_ids: list[str],
    default_tab_id: str | None,
) -> UserCustomerAnalyticsConfig:
    errors: list[str] = []
    _validate_tab_ids("ordered_tab_ids", ordered_tab_ids, errors)
    _validate_tab_ids("hidden_tab_ids", hidden_tab_ids, errors)
    if default_tab_id is not None and not _is_tab_id(default_tab_id):
        errors.append("default_tab_id must use a system: or view: identifier.")
    if errors:
        raise ValueError("; ".join(errors))

    config = get_or_create_config(team_id=team_id, user_id=user_id)
    config.properties = {
        **config.properties,
        ACCOUNT_DETAIL_TABS_KEY: {
            "ordered_tab_ids": ordered_tab_ids,
            "hidden_tab_ids": hidden_tab_ids,
            "default_tab_id": default_tab_id,
        },
    }
    config.save(update_fields=["properties", "updated_at"])
    return config


def _is_tab_id(tab_id: str) -> bool:
    if tab_id in ACCOUNT_DETAIL_SYSTEM_TAB_IDS:
        return True
    if not tab_id.startswith("view:"):
        return False
    try:
        UUID(tab_id.removeprefix("view:"))
    except ValueError:
        return False
    return True


def _read_tab_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tab_ids: list[str] = []
    for tab_id in value:
        if isinstance(tab_id, str) and _is_tab_id(tab_id) and tab_id not in tab_ids:
            tab_ids.append(tab_id)
        if len(tab_ids) == MAX_ACCOUNT_DETAIL_TAB_IDS:
            break
    return tab_ids


def _validate_tab_ids(field: str, tab_ids: list[str], errors: list[str]) -> None:
    if len(tab_ids) > MAX_ACCOUNT_DETAIL_TAB_IDS:
        errors.append(f"{field} can contain at most {MAX_ACCOUNT_DETAIL_TAB_IDS} items.")
    if len(set(tab_ids)) != len(tab_ids):
        errors.append(f"{field} cannot contain duplicates.")
    if any(not _is_tab_id(tab_id) for tab_id in tab_ids):
        errors.append(f"{field} contains an invalid tab identifier.")


def _read_send_time(stored: dict[str, Any]) -> str:
    value = stored.get("send_time")
    if isinstance(value, str):
        try:
            parsed = datetime.strptime(value, contracts.TASK_DIGEST_SEND_TIME_FORMAT)
        except ValueError:
            return DEFAULT_TASK_DIGEST.send_time
        return parsed.strftime(contracts.TASK_DIGEST_SEND_TIME_FORMAT)
    return DEFAULT_TASK_DIGEST.send_time
