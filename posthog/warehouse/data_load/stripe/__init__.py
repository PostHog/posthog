""" This source uses Stripe API and dlt to load data such as Customer, Subscription, Event etc. to the database and to calculate the MRR and churn rate. """

from typing import Any, Dict, Generator, Optional, Tuple, Iterable

import dlt
import stripe
from dlt.extract.source import DltResource

from pendulum import DateTime

from .helper import pagination, transform_date
from .settings import ENDPOINTS, INCREMENTAL_ENDPOINTS


@dlt.source
def stripe_source(
    endpoints: Tuple[str, ...] = ENDPOINTS,
    stripe_secret_key: str = dlt.secrets.value,
    start_date: Optional[DateTime] = None,
    end_date: Optional[DateTime] = None,
) -> Iterable[DltResource]:
    """
    Retrieves data from the Stripe API for the specified endpoints.

    For all endpoints, Stripe API responses do not provide the key "updated",
    so in most cases, we are forced to load the data in 'replace' mode.
    This source is suitable for all types of endpoints, including 'Events', 'Invoice', etc.
    but these endpoints can also be loaded in incremental mode (see source incremental_stripe_source).

    Args:
        endpoints (Tuple[str, ...]): A tuple of endpoint names to retrieve data from. Defaults to most popular Stripe API endpoints.
        stripe_secret_key (str): The API access token for authentication. Defaults to the value in the `dlt.secrets` object.
        start_date (Optional[DateTime]): An optional start date to limit the data retrieved. Format: datetime(YYYY, MM, DD). Defaults to None.
        end_date (Optional[DateTime]): An optional end date to limit the data retrieved. Format: datetime(YYYY, MM, DD). Defaults to None.

    Returns:
        Iterable[DltResource]: Resources with data that was created during the period greater than or equal to 'start_date' and less than 'end_date'.
    """
    stripe.api_key = stripe_secret_key
    stripe.api_version = "2022-11-15"

    def stripe_resource(
        endpoint: str,
    ) -> Generator[Dict[Any, Any], Any, None]:
        for item in pagination(endpoint, start_date, end_date):
            yield item

    for endpoint in endpoints:
        yield dlt.resource(
            stripe_resource,
            name=endpoint,
            write_disposition="replace",
        )(endpoint)


@dlt.source
def incremental_stripe_source(
    endpoints: Tuple[str, ...] = INCREMENTAL_ENDPOINTS,
    stripe_secret_key: str = dlt.secrets.value,
    initial_start_date: Optional[DateTime] = None,
    end_date: Optional[DateTime] = None,
) -> Iterable[DltResource]:
    """
    As Stripe API does not include the "updated" key in its responses,
    we are only able to perform incremental downloads from endpoints where all objects are uneditable.
    This source yields the resources with incremental loading based on "append" mode.
    You will load only the newest data without duplicating and without downloading a huge amount of data each time.

    Args:
        endpoints (tuple): A tuple of endpoint names to retrieve data from. Defaults to Stripe API endpoints with uneditable data.
        stripe_secret_key (str): The API access token for authentication. Defaults to the value in the `dlt.secrets` object.
        initial_start_date (Optional[DateTime]): An optional parameter that specifies the initial value for dlt.sources.incremental.
                            If parameter is not None, then load only data that were created after initial_start_date on the first run.
                            Defaults to None. Format: datetime(YYYY, MM, DD).
        end_date (Optional[DateTime]): An optional end date to limit the data retrieved.
                  Defaults to None. Format: datetime(YYYY, MM, DD).
    Returns:
        Iterable[DltResource]: Resources with only that data has not yet been loaded.
    """
    stripe.api_key = stripe_secret_key
    stripe.api_version = "2022-11-15"
    start_date_unix = (
        transform_date(initial_start_date) if initial_start_date is not None else -1
    )

    def incremental_resource(
        endpoint: str,
        created: Optional[Any] = dlt.sources.incremental(
            "created", initial_value=start_date_unix
        ),
    ) -> Generator[Dict[Any, Any], Any, None]:
        start_value = created.last_value
        for item in pagination(endpoint, start_date=start_value, end_date=end_date):
            yield item

    for endpoint in endpoints:
        yield dlt.resource(
            incremental_resource,
            name=endpoint,
            write_disposition="append",
            primary_key="id",
        )(endpoint)