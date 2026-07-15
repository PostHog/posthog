from collections.abc import Mapping

from posthog.slo.context import JsonValue
from posthog.slo.types import SloArea, SloConfig, SloOperation


def build_alert_check_slo(
    *,
    team_id: int,
    alert_id: str,
    distinct_id: str,
    alert_type: str,
    properties: Mapping[str, JsonValue] | None = None,
) -> SloConfig:
    event_properties = dict(properties or {})
    event_properties["alert_type"] = alert_type
    return SloConfig(
        operation=SloOperation.ALERT_CHECK,
        area=SloArea.ANALYTIC_PLATFORM,
        team_id=team_id,
        resource_id=alert_id,
        distinct_id=distinct_id,
        start_properties=event_properties.copy(),
        completion_properties=event_properties.copy(),
    )
