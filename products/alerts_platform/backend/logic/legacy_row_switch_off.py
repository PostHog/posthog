"""Switches off the source rows of the alerts the platform owns, a batch at a time, per team.

Every reader shows such an alert from its platform copy, so switching its row off changes nothing a
customer sees. A reader that still reads the row shows the alert as off, which is what this step is
there to find before the rows are deleted.
"""

from collections.abc import Callable, Collection, Sequence
from uuid import UUID

import structlog

from products.alerts_platform.backend.facade.contracts import LegacyRowSwitchOff, LegacyRowSwitchOffRun
from products.alerts_platform.backend.logic import platform_reads

logger = structlog.get_logger(__name__)

SwitchOffRows = Callable[[int, Sequence[UUID], bool], int]


def switch_off_team_rows(
    *, source_kind: str, team_ids: Collection[int], switch_off: SwitchOffRows, batch_size: int, apply: bool
) -> LegacyRowSwitchOffRun:
    teams: list[LegacyRowSwitchOff] = []
    failed: list[int] = []
    for team_id in team_ids:
        try:
            teams.append(
                _switch_off_team(
                    source_kind=source_kind,
                    team_id=team_id,
                    switch_off=switch_off,
                    batch_size=batch_size,
                    apply=apply,
                )
            )
        except Exception:
            logger.exception("legacy_row_switch_off.failed", source_kind=source_kind, team_id=team_id)
            failed.append(team_id)
    return LegacyRowSwitchOffRun(teams=tuple(teams), failed_team_ids=tuple(failed))


def _switch_off_team(
    *, source_kind: str, team_id: int, switch_off: SwitchOffRows, batch_size: int, apply: bool
) -> LegacyRowSwitchOff:
    owned = [
        key.legacy_configuration_id for key in platform_reads.owned_copy_keys(team_id=team_id, source_kind=source_kind)
    ]
    switched_off = sum(
        switch_off(team_id, owned[start : start + batch_size], apply) for start in range(0, len(owned), batch_size)
    )
    logger.info(
        "legacy_row_switch_off.team",
        source_kind=source_kind,
        team_id=team_id,
        owned_alerts=len(owned),
        switched_off=switched_off,
        applied=apply,
    )
    return LegacyRowSwitchOff(team_id=team_id, owned_alerts=len(owned), switched_off=switched_off)
