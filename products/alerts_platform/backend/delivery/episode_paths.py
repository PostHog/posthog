"""The path each firing delivers through, stored so a firing and its resolve take the same one."""

from collections.abc import Callable
from datetime import datetime

from products.alerts_platform.backend.facade.contracts import DeliveryPath
from products.alerts_platform.backend.models import PlatformAlertDeliveryPath


def episode_path(
    *,
    team_id: int,
    configuration_id: str,
    grouping_key: str,
    episode_started_at: datetime,
    choose: Callable[[], DeliveryPath],
) -> DeliveryPath:
    """The path this firing already took, or the one `choose` picks now, stored for the rest of it.

    The first writer wins, so two deliveries of one firing that race agree on the path.
    """
    stored = (
        PlatformAlertDeliveryPath.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, grouping_key=grouping_key, episode_started_at=episode_started_at)
        .values_list("path", flat=True)
        .first()
    )
    if stored is not None:
        return DeliveryPath(stored)
    row, _ = PlatformAlertDeliveryPath.objects.for_team(team_id).get_or_create(
        configuration_id=configuration_id,
        grouping_key=grouping_key,
        episode_started_at=episode_started_at,
        defaults={"team_id": team_id, "path": choose()},
    )
    return DeliveryPath(row.path)
