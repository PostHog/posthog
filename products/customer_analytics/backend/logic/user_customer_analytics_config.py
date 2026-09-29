from collections.abc import Sequence
from datetime import datetime, time
from typing import Any, cast
from uuid import UUID

from django.db import transaction

from posthog.models.scoping.manager import resolve_effective_team_id

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import AccountPropertyPinKind, TaskDigestCadence
from products.customer_analytics.backend.logic.account_property_pins import validate_pinned_properties
from products.customer_analytics.backend.models import TeamCustomerAnalyticsConfig, UserCustomerAnalyticsConfig

PINNED_PROPERTIES_KEY = "pinned_properties"
PINNED_PROPERTIES_OVERRIDE_KEY = "pinned_properties_override"
TASK_DIGEST_KEY = "task_digest"
DEFAULT_TASK_DIGEST = contracts.TaskDigestPreferences()


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
    *, team_id: int, user_id: int, references: Sequence[tuple[AccountPropertyPinKind, UUID]]
) -> UserCustomerAnalyticsConfig:
    validate_pinned_properties(team_id=team_id, references=references)
    config = get_or_create_config(team_id=team_id, user_id=user_id)
    config.properties = {
        **config.properties,
        PINNED_PROPERTIES_KEY: [{"kind": kind.value, "id": str(definition_id)} for kind, definition_id in references],
        PINNED_PROPERTIES_OVERRIDE_KEY: True,
    }
    config.pinned_custom_property_definition_ids = [
        definition_id for kind, definition_id in references if kind == AccountPropertyPinKind.CUSTOM_PROPERTY
    ]
    config.save(update_fields=["properties", "pinned_custom_property_definition_ids", "updated_at"])
    return config


def read_pinned_properties(config: UserCustomerAnalyticsConfig) -> list[dict[str, str]]:
    stored = config.properties.get(PINNED_PROPERTIES_KEY)
    if isinstance(stored, list) and (
        stored
        or config.properties.get(PINNED_PROPERTIES_OVERRIDE_KEY) is True
        or config.pinned_custom_property_definition_ids
    ):
        return cast(list[dict[str, str]], stored)
    defaults = (
        TeamCustomerAnalyticsConfig.objects.filter(team_id=config.team_id)
        .values_list("default_pinned_properties", flat=True)
        .first()
    )
    return cast(list[dict[str, str]], defaults) if isinstance(defaults, list) else []


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


def _read_send_time(stored: dict[str, Any]) -> str:
    value = stored.get("send_time")
    if isinstance(value, str):
        try:
            parsed = datetime.strptime(value, contracts.TASK_DIGEST_SEND_TIME_FORMAT)
        except ValueError:
            return DEFAULT_TASK_DIGEST.send_time
        return parsed.strftime(contracts.TASK_DIGEST_SEND_TIME_FORMAT)
    return DEFAULT_TASK_DIGEST.send_time
