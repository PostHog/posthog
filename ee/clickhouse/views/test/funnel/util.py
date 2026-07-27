import dataclasses
from typing import Any, Literal, Optional, TypedDict, Union

from django.test.client import Client

from posthog.models.property import GroupTypeIndex


class EventPattern(TypedDict, total=False):
    id: str
    type: Union[Literal["events"], Literal["actions"]]
    order: int
    properties: dict[str, Any]


@dataclasses.dataclass
class FunnelRequest:
    events: str
    date_from: str
    insight: str
    aggregation_group_type_index: Optional[GroupTypeIndex] = None
    date_to: Optional[str] = None
    properties: Optional[str] = None
    funnel_order_type: Optional[str] = None


def get_funnel(client: Client, team_id: int, request: FunnelRequest):
    return client.post(
        f"/api/projects/{team_id}/insights/funnel",
        data={key: value for key, value in dataclasses.asdict(request).items() if value is not None},
    )


def get_funnel_ok(client: Client, team_id: int, request: FunnelRequest) -> dict[str, Any]:
    response = get_funnel(client=client, team_id=team_id, request=request)

    assert response.status_code == 200, response.content
    res = response.json()
    final = {}

    for step in res["result"]:
        final[step["name"]] = step

    return final
