"""Stripe analytics source helpers"""

from typing import Any, Dict, Optional, Union, Iterable

import stripe
import dlt
from dlt.common import pendulum
from dlt.sources import DltResource
from pendulum import DateTime

stripe.api_version = "2022-11-15"


def transform_date(date: Union[str, DateTime, int]) -> int:
    if isinstance(date, str):
        date = pendulum.from_format(date, "%Y-%m-%dT%H:%M:%SZ")
    if isinstance(date, DateTime):
        # convert to unix timestamp
        date = int(date.timestamp())
    return date


def stripe_pagination(
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

    should_continue = True

    def stripe_get_data(
        api_key: str,
        resource: str,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[Any, Any]:
        nonlocal should_continue
        nonlocal starting_after

        if start_date:
            start_date = transform_date(start_date)
        if end_date:
            end_date = transform_date(end_date)

        if resource == "Subscription":
            kwargs.update({"status": "all"})

        _resource = getattr(stripe, resource)
        resource_dict = _resource.list(
            api_key=api_key,
            created={"gte": start_date, "lt": end_date},
            limit=100,
            **kwargs,
        )
        response = dict(resource_dict)

        if not response["has_more"]:
            should_continue = False

        if len(response["data"]) > 0:
            starting_after = response["data"][-1]["id"]

        return response["data"]

    while should_continue:
        yield stripe_get_data(
            api_key,
            endpoint,
            start_date=start_date,
            end_date=end_date,
            starting_after=starting_after,
        )


@dlt.source
def stripe_source(
    api_key: str,
    endpoint: str,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    starting_after: Optional[str] = None,
) -> Iterable[DltResource]:
    return dlt.resource(
        stripe_pagination,
        name=endpoint,
        write_disposition="append",
        columns={
            "metadata": {
                "data_type": "complex",
                "nullable": True,
            }
        },
    )(
        api_key=api_key,
        endpoint=endpoint,
        start_date=start_date,
        end_date=end_date,
        starting_after=starting_after,
    )
