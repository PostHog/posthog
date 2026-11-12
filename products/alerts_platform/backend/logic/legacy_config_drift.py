"""Compares each platform-owned alert's source row with its platform copy, setting by setting.

While both rows exist, every edit writes both, so any difference means a writer missed one. Reads
move to the copy, and the source rows stop being read and written, only once this finds none.

The expected copy comes from the same upsert a source writes, through `stored_settings_of`, so the
mapping from a row to its copy is stated once.
"""

import json
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import LegacyCopyExpectation, LegacyDriftSource, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.logic.platform_lifecycle import stored_settings_of
from products.alerts_platform.backend.models import PlatformAlertConfiguration

# The settings a source row has no counterpart for, and so cannot drift on.
COPY_MISSING: Final = "copy_missing"
NO_PLATFORM_FORM: Final = "no_platform_form"

_SOURCE_CONFIG: Final = "source_config"
# Deep enough to name a bound, a comparison or a filter, without splitting one bound into its parts.
_SOURCE_CONFIG_DEPTH: Final = 2
_MISSING: Final = object()

_sources: dict[SourceKind, LegacyDriftSource] = {}


def register(source: SourceKind, provider: LegacyDriftSource) -> None:
    registered = _sources.get(source)
    if registered is not None and registered is not provider:
        raise RuntimeError(f"A different drift source is already registered for {source} alerts.")
    _sources[source] = provider


def registered_sources() -> tuple[SourceKind, ...]:
    return tuple(_sources)


@frozen
class SettingDrift:
    """The alerts of one team and source whose copy differs from their row on one setting."""

    team_id: int
    source_kind: SourceKind
    setting: str
    count: int
    sample_ids: tuple[UUID, ...]


@frozen
class DriftReport:
    compared: int
    drifted: int
    drifts: tuple[SettingDrift, ...]


def report_drift(
    *, source_kinds: Sequence[SourceKind], team_id: int | None, batch_size: int, sample_size: int, now: datetime
) -> DriftReport:
    """Reads every platform-owned row of the named sources, and its copy, and writes nothing."""
    drifted_ids: dict[tuple[int, SourceKind, str], list[UUID]] = defaultdict(list)
    compared = drifted = 0
    for source_kind in source_kinds:
        for batch in _sources[source_kind](team_id, batch_size):
            copies = _copies_of(batch)
            for expectation in batch:
                compared += 1
                settings = drifted_settings(expectation, copies.get(expectation.legacy_configuration_id), now=now)
                drifted += bool(settings)
                for setting in settings:
                    drifted_ids[(expectation.team_id, source_kind, setting)].append(expectation.legacy_configuration_id)
    drifts = tuple(
        SettingDrift(
            team_id=team,
            source_kind=source_kind,
            setting=setting,
            count=len(ids),
            sample_ids=tuple(sorted(ids)[:sample_size]),
        )
        for (team, source_kind, setting), ids in sorted(drifted_ids.items())
    )
    return DriftReport(compared=compared, drifted=drifted, drifts=drifts)


def drifted_settings(expectation: LegacyCopyExpectation, copy: Mapping[str, Any] | None, *, now: datetime) -> list[str]:
    """The settings on which `copy`, a stored copy's columns, differs from what its row says."""
    if copy is None:
        return [COPY_MISSING]
    if expectation.upsert is None:
        return [NO_PLATFORM_FORM]
    try:
        expected = stored_settings_of(expectation.upsert)
    except ValueError:
        return [NO_PLATFORM_FORM]
    expected.update(expectation.extra_columns, team_id=expectation.team_id, owner=PlatformAlertOwner.PLATFORM.value)
    # As the JSON column stores it, so a tuple or a date in the upsert compares equal to what was written.
    expected_config = json.loads(json.dumps(expected.pop(_SOURCE_CONFIG), cls=DjangoJSONEncoder))
    drifted = [
        column
        for column, value in expected.items()
        if _comparable(column, value, now) != _comparable(column, copy[column], now)
    ]
    expected_leaves = _leaves(expected_config, _SOURCE_CONFIG, _SOURCE_CONFIG_DEPTH)
    stored_leaves = _leaves(copy[_SOURCE_CONFIG], _SOURCE_CONFIG, _SOURCE_CONFIG_DEPTH)
    drifted.extend(
        path
        for path in sorted(expected_leaves.keys() | stored_leaves.keys())
        if expected_leaves.get(path, _MISSING) != stored_leaves.get(path, _MISSING)
    )
    return drifted


def _comparable(column: str, value: Any, now: datetime) -> Any:
    # A snooze that has ended mutes nothing, whichever side still holds it.
    if column == "snooze_until" and value is not None and value <= now:
        return None
    return value


def _leaves(value: Any, path: str, depth: int) -> dict[str, Any]:
    if not isinstance(value, dict) or depth == 0:
        return {path: value}
    leaves: dict[str, Any] = {}
    for key, child in value.items():
        leaves.update(_leaves(child, f"{path}.{key}", depth - 1))
    return leaves


def _copies_of(batch: Collection[LegacyCopyExpectation]) -> dict[UUID, dict[str, Any]]:
    # Every column, because a source's `extra_columns` may name any of them.
    rows = (
        PlatformAlertConfiguration.objects.unscoped()
        .filter(
            team_id__in={expectation.team_id for expectation in batch},
            legacy_configuration_id__in=[expectation.legacy_configuration_id for expectation in batch],
        )
        .values()
    )
    return {row["legacy_configuration_id"]: row for row in rows}
