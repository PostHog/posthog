"""Compares each platform-owned alert's source row with its platform copy, setting by setting.

Reads move to the copy, and the source rows stop being read and written, only once this finds none.
"""

import json
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import LegacyCopyExpectation, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.logic.legacy_drift_sources import provider_of
from products.alerts_platform.backend.logic.platform_lifecycle import stored_settings_of
from products.alerts_platform.backend.models import PlatformAlertConfiguration

COPY_MISSING: Final = "copy_missing"
NO_PLATFORM_FORM: Final = "no_platform_form"

_SOURCE_CONFIG: Final = "source_config"
_JSON_COLUMNS: Final = (_SOURCE_CONFIG, "schedule_restriction")
# Deep enough to name a bound, a comparison or a filter, without splitting one bound into its parts.
_SOURCE_CONFIG_DEPTH: Final = 2
_MISSING: Final = object()


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
    counts: dict[tuple[int, SourceKind, str], int] = {}
    # Rows arrive in id order, so the first ids kept are the lowest.
    samples: dict[tuple[int, SourceKind, str], list[UUID]] = {}
    compared = drifted = 0
    for source_kind in source_kinds:
        provider, after = provider_of(source_kind), None
        while batch := provider(team_id, after, batch_size):
            after = batch[-1].legacy_configuration_id
            copies = _copies_of(batch)
            for expectation in batch:
                compared += 1
                settings = drifted_settings(expectation, copies.get(expectation.legacy_configuration_id), now=now)
                drifted += bool(settings)
                for setting in settings:
                    key = (expectation.team_id, source_kind, setting)
                    counts[key] = counts.get(key, 0) + 1
                    sample = samples.setdefault(key, [])
                    if len(sample) < sample_size:
                        sample.append(expectation.legacy_configuration_id)
    drifts = tuple(
        SettingDrift(
            team_id=team, source_kind=kind, setting=setting, count=count, sample_ids=tuple(samples[team, kind, setting])
        )
        for (team, kind, setting), count in sorted(counts.items())
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
    stored = {column: copy[column] for column in expected}
    for side in (expected, stored):
        # A snooze that has ended mutes nothing, whichever side still holds it.
        if side["snooze_until"] is not None and side["snooze_until"] <= now:
            side["snooze_until"] = None
    # As the JSON column stores it, so a tuple in the upsert compares equal to the list written.
    for column in _JSON_COLUMNS:
        expected[column] = json.loads(json.dumps(expected[column]))
    drifted = [column for column in expected if column != _SOURCE_CONFIG and expected[column] != stored[column]]
    expected_leaves = _leaves(expected[_SOURCE_CONFIG], _SOURCE_CONFIG, _SOURCE_CONFIG_DEPTH)
    stored_leaves = _leaves(stored[_SOURCE_CONFIG], _SOURCE_CONFIG, _SOURCE_CONFIG_DEPTH)
    drifted.extend(
        path
        for path in sorted(expected_leaves.keys() | stored_leaves.keys())
        if expected_leaves.get(path, _MISSING) != stored_leaves.get(path, _MISSING)
    )
    return drifted


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
