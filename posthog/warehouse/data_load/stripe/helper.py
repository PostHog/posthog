"""Stripe analytics source helpers"""

from typing import Any, Dict, Iterable, Optional, Union

import stripe
from dlt.common import pendulum
from dlt.common.typing import TDataItem
from pendulum import DateTime


def pagination(endpoint: str, start_date: Optional[Any] = None, end_date: Optional[Any] = None) -> Iterable[TDataItem]:
    """
    Retrieves data from an endpoint with pagination.

    Args:
        endpoint (str): The endpoint to retrieve data from.
        start_date (Optional[Any]): An optional start date to limit the data retrieved. Defaults to None.
        end_date (Optional[Any]): An optional end date to limit the data retrieved. Defaults to None.

    Returns:
        Iterable[TDataItem]: Data items retrieved from the endpoint.
    """
    starting_after = None
    while True:
        response = stripe_get_data(
            endpoint,
            start_date=start_date,
            end_date=end_date,
            starting_after=starting_after,
        )

        if len(response["data"]) > 0:
            starting_after = response["data"][-1]["id"]
        yield response["data"]

        if not response["has_more"]:
            break


def transform_date(date: Union[str, DateTime, int]) -> int:
    if isinstance(date, str):
        date = pendulum.from_format(date, "%Y-%m-%dT%H:%M:%SZ")
    if isinstance(date, DateTime):
        # convert to unix timestamp
        date = int(date.timestamp())
    return date


def stripe_get_data(
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

    resource_dict = getattr(stripe, resource).list(created={"gte": start_date, "lt": end_date}, limit=100, **kwargs)
    return dict(resource_dict)
