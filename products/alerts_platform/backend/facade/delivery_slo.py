from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from posthog.slo.context import JsonValue, SloHandle, SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation
from posthog.utils import get_instance_region


@contextmanager
def alert_delivery_slo(
    *,
    alert_type: str,
    notification_action: str,
    distinct_id: str,
    team_id: int,
    resource_id: str,
    properties: Mapping[str, JsonValue] | None = None,
) -> Iterator[SloHandle]:
    with slo_operation(
        spec=SloSpec(
            distinct_id=distinct_id,
            area=SloArea.ANALYTIC_PLATFORM,
            operation=SloOperation.ALERT_DELIVERY,
            team_id=team_id,
            resource_id=resource_id,
        ),
        properties={
            **dict(properties or {}),
            "alert_type": alert_type,
            "notification_action": notification_action,
            "region": (get_instance_region() or "HOBBY").upper(),
        },
    ) as slo:
        yield slo
