"""Writes to a configuration through the API, for the configurations the platform owns.

A configuration its source owns is a copy of the source's own row, which the source's API writes
and the next check reads back. Writing the copy here would fork it, so those are refused.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from uuid import UUID

from django.db import transaction

from pydantic import ValidationError as PydanticValidationError

from products.alerts_platform.backend.facade.contracts import (
    DEFAULT_MAX_INSTANCES,
    MAX_EVALUATION_PERIODS,
    Grouping,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationView,
    PlatformAlertNotEditable,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.facade.scheduling import validate_and_normalize_schedule_restriction
from products.alerts_platform.backend.logic import platform_reads, source_configs
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration, PlatformAlertThread


def edit_of(configuration: PlatformAlertConfiguration) -> PlatformAlertConfigurationEdit:
    return PlatformAlertConfigurationEdit(
        name=configuration.name,
        enabled=configuration.enabled,
        source_config=configuration.source_config,
        grouping=Grouping.from_stored(configuration.grouping),
        schedule_restriction=configuration.schedule_restriction,
        evaluation_periods=configuration.evaluation_periods,
        datapoints_to_alarm=configuration.datapoints_to_alarm,
        cooldown_minutes=configuration.cooldown_minutes,
    )


def _validated(
    source_kind: SourceKind, current: PlatformAlertConfigurationEdit, edit: PlatformAlertConfigurationEdit
) -> PlatformAlertConfigurationEdit:
    spec = source_configs.spec(source_kind)
    if spec is None:
        raise PlatformAlertNotEditable(f"{source_kind} alerts cannot be edited through this API.")
    for name, value in (
        ("evaluation_periods", edit.evaluation_periods),
        ("datapoints_to_alarm", edit.datapoints_to_alarm),
    ):
        if not 1 <= value <= MAX_EVALUATION_PERIODS:
            raise InvalidPlatformAlertEdit(name, f"Must be between 1 and {MAX_EVALUATION_PERIODS}.")
    if edit.datapoints_to_alarm > edit.evaluation_periods:
        raise InvalidPlatformAlertEdit("datapoints_to_alarm", "Cannot exceed evaluation_periods.")
    if edit.grouping.max_instances > DEFAULT_MAX_INSTANCES:
        raise InvalidPlatformAlertEdit("grouping", f"max_instances must be at most {DEFAULT_MAX_INSTANCES}.")
    if edit.cooldown_minutes < 0:
        raise InvalidPlatformAlertEdit("cooldown_minutes", "Cannot be negative.")
    try:
        schedule_restriction = validate_and_normalize_schedule_restriction(edit.schedule_restriction)
    except ValueError as error:
        raise InvalidPlatformAlertEdit("schedule_restriction", str(error)) from error
    source_config = edit.source_config
    # Settings the edit leaves alone may predate the schema, and must not block an unrelated change.
    if source_config != current.source_config:
        try:
            parsed = spec.model.model_validate(source_config)
        except PydanticValidationError as error:
            first = error.errors()[0]
            location = ".".join(str(part) for part in first["loc"])
            raise InvalidPlatformAlertEdit("source_config", f"Invalid at `{location}`: {first['msg']}") from error
        source_config = parsed.model_dump(mode="json", exclude_unset=True)
    validated = replace(edit, source_config=source_config, schedule_restriction=schedule_restriction)
    spec.validate(validated)
    return validated


def update_configuration(
    *,
    team_id: int,
    source_kinds: Sequence[str],
    configuration_id: UUID,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
) -> PlatformAlertConfigurationView | None:
    """Applies `change` to the configuration's current settings under its row lock.

    None when the configuration does not exist or its kind is not among `source_kinds`. Taking a
    function rather than the new settings lets a partial update merge with what is stored inside
    the lock, so two partial updates of different fields both survive.
    """
    with transaction.atomic():
        configuration = (
            PlatformAlertConfiguration.objects.for_team(team_id, canonical=True)
            .select_for_update()
            .filter(id=configuration_id, source_kind__in=list(source_kinds))
            .first()
        )
        if configuration is None:
            return None
        if configuration.owner != PlatformAlertOwner.PLATFORM:
            raise PlatformAlertNotEditable(
                f"This alert is managed by the {configuration.source_kind} product. Edit it there."
            )
        current = edit_of(configuration)
        edit = _validated(SourceKind(configuration.source_kind), current, change(current))

        if (edit.grouping.mode, edit.grouping.keys) != (current.grouping.mode, current.grouping.keys):
            # The old keys never come back from a check, so each old instance would resolve and
            # announce a recovery that did not happen. They go, threads included, without a message.
            PlatformAlert.objects.for_team(team_id, canonical=True).filter(configuration=configuration).delete()
            PlatformAlertThread.objects.for_team(team_id, canonical=True).filter(configuration=configuration).delete()

        configuration.name = edit.name
        configuration.enabled = edit.enabled
        configuration.source_config = edit.source_config
        configuration.grouping = edit.grouping.to_stored()
        configuration.schedule_restriction = edit.schedule_restriction
        configuration.evaluation_periods = edit.evaluation_periods
        configuration.datapoints_to_alarm = edit.datapoints_to_alarm
        configuration.cooldown_minutes = edit.cooldown_minutes
        configuration.save(
            update_fields=[
                "name",
                "enabled",
                "source_config",
                "grouping",
                "schedule_restriction",
                "evaluation_periods",
                "datapoints_to_alarm",
                "cooldown_minutes",
                "updated_at",
            ]
        )

    return platform_reads.get_configuration(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id
    )
