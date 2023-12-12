"""Stripe analytics source helpers"""

from typing import Any, Dict, Optional, Union

import stripe
from dlt.common import pendulum
from pendulum import DateTime
from asgiref.sync import sync_to_async

stripe.api_version = "2022-11-15"


async def stripe_pagination(
    api_key: str,
    endpoint: str,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    starting_after: Optional[str] = None,
):
    """
    Retrieves data from an endpoint with pagination.

    Args:
        endpoint (str): The endpoint to retrieve data from.
        start_date (Optional[Any]): An optional start date to limit the data retrieved. Defaults to None.
        end_date (Optional[Any]): An optional end date to limit the data retrieved. Defaults to None.

    Returns:
        Iterable[TDataItem]: Data items retrieved from the endpoint.
    """
    while True:
        response = await stripe_get_data(
            api_key,
            endpoint,
            start_date=start_date,
            end_date=end_date,
            starting_after=starting_after,
        )

        if len(response["data"]) > 0:
            starting_after = response["data"][-1]["id"]
        yield response["data"], starting_after

        if not response["has_more"]:
            break


def transform_date(date: Union[str, DateTime, int]) -> int:
    if isinstance(date, str):
        date = pendulum.from_format(date, "%Y-%m-%dT%H:%M:%SZ")
    if isinstance(date, DateTime):
        # convert to unix timestamp
        date = int(date.timestamp())
    return date


async def stripe_get_data(
    api_key: str,
    resource: str,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[Any, Any]:
    if start_date:
        start_date = transform_date(start_date)
    if end_date:
        end_date = transform_date(end_date)

    if resource == "Subscription":
        kwargs.update({"status": "all"})

    _resource = getattr(stripe, resource)
    resource_dict = await sync_to_async(_resource.list)(
        api_key=api_key,
        created={"gte": start_date, "lt": end_date},
        limit=100,
        **kwargs,  # type: ignore
    )
    return dict(resource_dict)
