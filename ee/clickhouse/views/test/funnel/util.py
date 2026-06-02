import dataclasses
from typing import Any, Literal, Optional, TypedDict, Union

from django.test.client import Client

from posthog.constants import FunnelCorrelationType
from posthog.models.property import GroupTypeIndex

from ee.clickhouse.queries.funnels.funnel_correlation import EventOddsRatioSerialized


class EventPattern(TypedDict, total=False):
    id: str
    type: Union[Literal["events"], Literal["actions"]]
    order: int
    properties: dict[str, Any]


@dataclasses.dataclass
class FunnelCorrelationRequest:
    # Needs to be json encoded list of `EventPattern`s
    events: str
    date_to: str
    funnel_step: Optional[int] = None
    date_from: Optional[str] = None
    funnel_correlation_type: Optional[FunnelCorrelationType] = None
    # Needs to be json encoded list of `str`s
    funnel_correlation_names: Optional[str] = None
    funnel_correlation_event_names: Optional[str] = None


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


def get_funnel_correlation(client: Client, team_id: int, request: FunnelCorrelationRequest):
    return client.get(
        f"/api/projects/{team_id}/insights/funnel/correlation",
        data={key: value for key, value in dataclasses.asdict(request).items() if value is not None},
    )


def get_funnel_correlation_ok(client: Client, team_id: int, request: FunnelCorrelationRequest) -> dict[str, Any]:
    response = get_funnel_correlation(client=client, team_id=team_id, request=request)

    assert response.status_code == 200, response.content
    return response.json()


def get_people_for_correlation_ok(client: Client, correlation: EventOddsRatioSerialized) -> dict[str, Any]:
    """
    Helper for getting people for a correlation. Note we keep checking to just
    inclusion of name, to make the stable to changes in other people props.
    """
    success_people_url = correlation["success_people_url"]
    failure_people_url = correlation["failure_people_url"]

    if not success_people_url or not failure_people_url:
        return {}

    success_people_response = client.get(success_people_url)
    assert success_people_response.status_code == 200, success_people_response.content

    failure_people_response = client.get(failure_people_url)
    assert failure_people_response.status_code == 200, failure_people_response.content

    return {
        "success": sorted([person["name"] for person in success_people_response.json()["results"][0]["people"]]),
        "failure": sorted([person["name"] for person in failure_people_response.json()["results"][0]["people"]]),
    }
