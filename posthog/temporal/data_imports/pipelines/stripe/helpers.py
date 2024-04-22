"""Stripe analytics source helpers"""

from typing import Any, Dict, Optional, Union, Iterable, Tuple

import stripe
import dlt
from dlt.common import pendulum
from dlt.sources import DltResource
from pendulum import DateTime
from asgiref.sync import sync_to_async
from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.temporal.data_imports.pipelines.helpers import check_limit
from posthog.temporal.data_imports.pipelines.stripe.settings import INCREMENTAL_ENDPOINTS
from posthog.warehouse.models import ExternalDataJob

stripe.api_version = "2022-11-15"


def transform_date(date: Union[str, DateTime, int]) -> int:
    if isinstance(date, str):
        date = pendulum.from_format(date, "%Y-%m-%dT%H:%M:%SZ")
    if isinstance(date, DateTime):
        # convert to unix timestamp
        date = int(date.timestamp())
    return date


async def stripe_get_data(
    api_key: str,
    account_id: str,
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
        stripe_account=account_id,
        created={"gte": start_date, "lt": end_date},
        limit=100,
        **kwargs,
    )
    response = dict(resource_dict)

    return response


async def stripe_pagination(
    api_key: str,
    account_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    source_id: str,
    starting_after: Optional[Any] = None,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
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

    logger = await bind_temporal_worker_logger(team_id)
    logger.info(f"Stripe: getting {endpoint}")

    if endpoint in INCREMENTAL_ENDPOINTS:
        _ending_before_state = dlt.current.resource_state(f"team_{team_id}_{source_id}_{endpoint}").setdefault(
            "ending_before", {"last_value": None}
        )
        _ending_before = _ending_before_state.get("last_value", None)
        _starting_after = None
    else:
        _starting_after = starting_after
        _ending_before = starting_after

    while True:
        if _ending_before is not None:
            logger.info(f"Stripe: getting {endpoint} before {_ending_before}")
        elif _starting_after is not None:
            logger.info(f"Stripe: getting {endpoint} after {_starting_after}")

        count = 0

        response = await stripe_get_data(
            api_key,
            account_id,
            endpoint,
            ending_before=_ending_before,
            starting_after=_starting_after,
            start_date=start_date,
            end_date=end_date,
        )

        if len(response["data"]) > 0:
            if endpoint in INCREMENTAL_ENDPOINTS:
                if _starting_after is None and _ending_before is None:
                    _ending_before_state["last_value"] = response["data"][0]["id"]

                if _ending_before is not None:
                    _ending_before = response["data"][0]["id"]
                else:
                    _starting_after = response["data"][-1]["id"]
            else:
                _starting_after = response["data"][-1]["id"]

        yield response["data"]

        count, status = await check_limit(
            team_id=team_id,
            job_id=job_id,
            new_count=count + len(response["data"]),
        )

        if not response["has_more"] or status == ExternalDataJob.Status.CANCELLED:
            break


@dlt.source(max_table_nesting=0)
def stripe_source(
    api_key: str,
    account_id: str,
    endpoints: Tuple[str, ...],
    team_id,
    job_id,
    source_id,
    starting_after: Optional[str] = None,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
) -> Iterable[DltResource]:
    for endpoint in endpoints:
        yield dlt.resource(
            stripe_pagination,
            name=endpoint,
            write_disposition="append",
        )(
            api_key=api_key,
            account_id=account_id,
            endpoint=endpoint,
            team_id=team_id,
            job_id=job_id,
            source_id=source_id,
            starting_after=starting_after,
            start_date=start_date,
            end_date=end_date,
        )
