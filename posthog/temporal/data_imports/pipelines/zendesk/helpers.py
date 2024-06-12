from typing import Optional
from collections.abc import Iterator, Iterable
from itertools import chain

import dlt
from dlt.common import pendulum
from dlt.common.time import ensure_pendulum_datetime
from dlt.common.typing import TDataItem, TAnyDateTime, TDataItems
from dlt.sources import DltResource

from posthog.temporal.common.logger import bind_temporal_worker_logger


from .api_helpers import process_ticket, process_ticket_field
from .talk_api import PaginationType, ZendeskAPIClient
from .credentials import TZendeskCredentials, ZendeskCredentialsOAuth

from .settings import (
    DEFAULT_START_DATE,
    CUSTOM_FIELDS_STATE_KEY,
    SUPPORT_ENDPOINTS,
    TALK_ENDPOINTS,
    INCREMENTAL_TALK_ENDPOINTS,
    SUPPORT_EXTRA_ENDPOINTS,
)


@dlt.source(max_table_nesting=0)
def zendesk_talk(
    credentials: TZendeskCredentials = dlt.secrets.value,
    start_date: Optional[TAnyDateTime] = DEFAULT_START_DATE,
    end_date: Optional[TAnyDateTime] = None,
) -> Iterable[DltResource]:
    """
    Retrieves data from Zendesk Talk for phone calls and voicemails.

    `start_date` argument can be used on its own or together with `end_date`. When both are provided
    data is limited to items updated in that time range.
    The range is "half-open", meaning elements equal and higher than `start_date` and elements lower than `end_date` are included.
    All resources opt-in to use Airflow scheduler if run as Airflow task

    Args:
        credentials: The credentials for authentication. Defaults to the value in the `dlt.secrets` object.
        start_date: The start time of the range for which to load. Defaults to January 1st 2000.
        end_date: The end time of the range for which to load data.
            If end time is not provided, the incremental loading will be enabled and after initial run, only new data will be retrieved
    Yields:
        DltResource: Data resources from Zendesk Talk.
    """

    # use the credentials to authenticate with the ZendeskClient
    zendesk_client = ZendeskAPIClient(credentials)
    start_date_obj = ensure_pendulum_datetime(start_date)
    end_date_obj = ensure_pendulum_datetime(end_date) if end_date else None

    # regular endpoints
    for key, talk_endpoint, item_name, cursor_paginated in TALK_ENDPOINTS:
        yield dlt.resource(
            talk_resource(
                zendesk_client,
                key,
                item_name or talk_endpoint,
                PaginationType.CURSOR if cursor_paginated else PaginationType.OFFSET,
            ),
            name=key,
            write_disposition="replace",
        )

    # adding incremental endpoints
    for key, talk_incremental_endpoint in INCREMENTAL_TALK_ENDPOINTS.items():
        yield dlt.resource(
            talk_incremental_resource,
            name=f"{key}_incremental",
            primary_key="id",
            write_disposition="merge",
        )(
            zendesk_client=zendesk_client,
            talk_endpoint_name=key,
            talk_endpoint=talk_incremental_endpoint,
            updated_at=dlt.sources.incremental[str](
                "updated_at",
                initial_value=start_date_obj.isoformat(),
                end_value=end_date_obj.isoformat() if end_date_obj else None,
                allow_external_schedulers=True,
            ),
        )


def talk_resource(
    zendesk_client: ZendeskAPIClient,
    talk_endpoint_name: str,
    talk_endpoint: str,
    pagination_type: PaginationType,
) -> Iterator[TDataItem]:
    """
    Loads data from a Zendesk Talk endpoint.

    Args:
        zendesk_client: An instance of ZendeskAPIClient for making API calls to Zendesk Talk.
        talk_endpoint_name: The name of the talk_endpoint.
        talk_endpoint: The actual URL ending of the endpoint.
        pagination: Type of pagination type used by endpoint

    Yields:
        TDataItem: Dictionary containing the data from the endpoint.
    """
    # send query and process it
    yield from zendesk_client.get_pages(talk_endpoint, talk_endpoint_name, pagination_type)


def talk_incremental_resource(
    zendesk_client: ZendeskAPIClient,
    talk_endpoint_name: str,
    talk_endpoint: str,
    updated_at: dlt.sources.incremental[str],
) -> Iterator[TDataItem]:
    """
    Loads data from a Zendesk Talk endpoint with incremental loading.

    Args:
        zendesk_client: An instance of ZendeskAPIClient for making API calls to Zendesk Talk.
        talk_endpoint_name: The name of the talk_endpoint.
        talk_endpoint: The actual URL ending of the endpoint.
        updated_at: Source for the last updated timestamp.

    Yields:
        TDataItem: Dictionary containing the data from the endpoint.
    """
    # send the request and process it
    for page in zendesk_client.get_pages(
        talk_endpoint,
        talk_endpoint_name,
        PaginationType.START_TIME,
        params={"start_time": ensure_pendulum_datetime(updated_at.last_value).int_timestamp},
    ):
        yield page
        if updated_at.end_out_of_range:
            return


@dlt.source(max_table_nesting=0)
def zendesk_chat(
    credentials: ZendeskCredentialsOAuth = dlt.secrets.value,
    start_date: Optional[TAnyDateTime] = DEFAULT_START_DATE,
    end_date: Optional[TAnyDateTime] = None,
) -> Iterable[DltResource]:
    """
    Retrieves data from Zendesk Chat for chat interactions.

    `start_date` argument can be used on its own or together with `end_date`. When both are provided
    data is limited to items updated in that time range.
    The range is "half-open", meaning elements equal and higher than `start_date` and elements lower than `end_date` are included.
    All resources opt-in to use Airflow scheduler if run as Airflow task

    Args:
        credentials: The credentials for authentication. Defaults to the value in the `dlt.secrets` object.
        start_date: The start time of the range for which to load. Defaults to January 1st 2000.
        end_date: The end time of the range for which to load data.
            If end time is not provided, the incremental loading will be enabled and after initial run, only new data will be retrieved

    Yields:
        DltResource: Data resources from Zendesk Chat.
    """

    # Authenticate
    zendesk_client = ZendeskAPIClient(credentials, url_prefix="https://www.zopim.com")
    start_date_obj = ensure_pendulum_datetime(start_date)
    end_date_obj = ensure_pendulum_datetime(end_date) if end_date else None

    yield dlt.resource(chats_table_resource, name="chats", write_disposition="merge")(
        zendesk_client,
        dlt.sources.incremental[str](
            "update_timestamp|updated_timestamp",
            initial_value=start_date_obj.isoformat(),
            end_value=end_date_obj.isoformat() if end_date_obj else None,
            allow_external_schedulers=True,
        ),
    )


def chats_table_resource(
    zendesk_client: ZendeskAPIClient,
    update_timestamp: dlt.sources.incremental[str],
) -> Iterator[TDataItems]:
    """
    Resource for Chats

    Args:
        zendesk_client: The Zendesk API client instance, used to make calls to Zendesk API.
        update_timestamp: Incremental source specifying the timestamp for incremental loading.

    Yields:
        dict: A dictionary representing each row of data.
    """
    chat_pages = zendesk_client.get_pages(
        "/api/v2/incremental/chats",
        "chats",
        PaginationType.START_TIME,
        params={
            "start_time": ensure_pendulum_datetime(update_timestamp.last_value).int_timestamp,
            "fields": "chats(*)",
        },
    )
    for page in chat_pages:
        yield page

        if update_timestamp.end_out_of_range:
            return


@dlt.source(max_table_nesting=0)
def zendesk_support(
    team_id: int,
    credentials: TZendeskCredentials = dlt.secrets.value,
    endpoints: tuple[str, ...] = (),
    pivot_ticket_fields: bool = True,
    start_date: Optional[TAnyDateTime] = DEFAULT_START_DATE,
    end_date: Optional[TAnyDateTime] = None,
) -> Iterable[DltResource]:
    """
    Retrieves data from Zendesk Support for tickets, users, brands, organizations, and groups.

    `start_date` argument can be used on its own or together with `end_date`. When both are provided
    data is limited to items updated in that time range.
    The range is "half-open", meaning elements equal and higher than `start_date` and elements lower than `end_date` are included.
    All resources opt-in to use Airflow scheduler if run as Airflow task

    Args:
        credentials: The credentials for authentication. Defaults to the value in the `dlt.secrets` object.
        load_all: Whether to load extra resources for the API. Defaults to True.
        pivot_ticket_fields: Whether to pivot the custom fields in tickets. Defaults to True.
        start_date: The start time of the range for which to load. Defaults to January 1st 2000.
        end_date: The end time of the range for which to load data.
            If end time is not provided, the incremental loading will be enabled and after initial run, only new data will be retrieved

    Returns:
        Sequence[DltResource]: Multiple dlt resources.
    """

    start_date_obj = ensure_pendulum_datetime(start_date)
    end_date_obj = ensure_pendulum_datetime(end_date) if end_date else None

    start_date_ts = start_date_obj.int_timestamp
    start_date_iso_str = start_date_obj.isoformat()
    end_date_ts: Optional[int] = None
    end_date_iso_str: Optional[str] = None
    if end_date_obj:
        end_date_ts = end_date_obj.int_timestamp
        end_date_iso_str = end_date_obj.isoformat()

    @dlt.resource(name="ticket_events", primary_key="id", write_disposition="append")
    async def ticket_events(
        zendesk_client: ZendeskAPIClient,
        timestamp: dlt.sources.incremental[int] = dlt.sources.incremental(  # noqa: B008
            "timestamp",
            initial_value=start_date_ts,
            end_value=end_date_ts,
            allow_external_schedulers=True,
        ),
    ):
        # URL For ticket events
        # 'https://d3v-dlthub.zendesk.com/api/v2/incremental/ticket_events.json?start_time=946684800'
        logger = await bind_temporal_worker_logger(team_id)
        logger.info("Zendesk: getting ticket_events")

        event_pages = zendesk_client.get_pages(
            "/api/v2/incremental/ticket_events.json",
            "ticket_events",
            PaginationType.STREAM,
            params={"start_time": timestamp.last_value},
        )
        for page in event_pages:
            yield page
            if timestamp.end_out_of_range:
                return

    @dlt.resource(
        name="tickets",
        primary_key="id",
        write_disposition="merge",
        columns={
            "tags": {"data_type": "complex"},
            "custom_fields": {"data_type": "complex"},
        },
    )
    async def ticket_table(
        zendesk_client: ZendeskAPIClient,
        pivot_fields: bool = True,
        updated_at: dlt.sources.incremental[pendulum.DateTime] = dlt.sources.incremental(  # noqa: B008
            "updated_at",
            initial_value=start_date_obj,
            end_value=end_date_obj,
            allow_external_schedulers=True,
        ),
    ):
        """
        Resource for tickets table. Uses DLT state to handle column renaming of custom fields to prevent changing the names of said columns.
        This resource uses pagination, loading and side loading to make API calls more efficient.

        Args:
            zendesk_client: The Zendesk API client instance, used to make calls to Zendesk API.
            pivot_fields: Indicates whether to pivot the custom fields in tickets. Defaults to True.
            per_page: The number of Ticket objects to load per page. Defaults to 1000.
            updated_at: Incremental source for the 'updated_at' column.
                Defaults to dlt.sources.incremental("updated_at", initial_value=start_date).

        Yields:
            TDataItem: Dictionary containing the ticket data.
        """
        logger = await bind_temporal_worker_logger(team_id)
        logger.info("Zendesk: getting tickets")

        fields_dict = dlt.current.source_state().setdefault(CUSTOM_FIELDS_STATE_KEY, {})
        # include_objects = ["users", "groups", "organisation", "brands"]
        ticket_pages = zendesk_client.get_pages(
            "/api/v2/incremental/tickets",
            "tickets",
            PaginationType.STREAM,
            params={"start_time": updated_at.last_value.int_timestamp},
        )
        for page in ticket_pages:
            yield [process_ticket(ticket, fields_dict, pivot_custom_fields=pivot_fields) for ticket in page]

            # stop loading when using end_value and end is reached
            if updated_at.end_out_of_range:
                return

    @dlt.resource(name="ticket_metric_events", primary_key="id", write_disposition="append")
    async def ticket_metric_table(
        zendesk_client: ZendeskAPIClient,
        time: dlt.sources.incremental[str] = dlt.sources.incremental(  # noqa: B008
            "time",
            initial_value=start_date_iso_str,
            end_value=end_date_iso_str,
            allow_external_schedulers=True,
        ),
    ):
        """
        Resource for ticket metric events table. Returns all the ticket metric events from the starting date,
        with the default starting date being January 1st of the current year.

        Args:
            zendesk_client: The Zendesk API client instance, used to make calls to Zendesk API.
            time: Incremental source for the 'time' column,
                indicating the starting date for retrieving ticket metric events.
                Defaults to dlt.sources.incremental("time", initial_value=start_date_iso_str).

        Yields:
            TDataItem: Dictionary containing the ticket metric event data.
        """
        logger = await bind_temporal_worker_logger(team_id)
        logger.info("Zendesk: getting ticket_metric_events")

        # "https://example.zendesk.com/api/v2/incremental/ticket_metric_events?start_time=1332034771"
        metric_event_pages = zendesk_client.get_pages(
            "/api/v2/incremental/ticket_metric_events",
            "ticket_metric_events",
            PaginationType.CURSOR,
            params={
                "start_time": ensure_pendulum_datetime(time.last_value).int_timestamp,
            },
        )
        for page in metric_event_pages:
            yield page

            if time.end_out_of_range:
                return

    async def ticket_fields_table(zendesk_client: ZendeskAPIClient):
        """
        Loads ticket fields data from Zendesk API.

        Args:
            zendesk_client: The Zendesk API client instance, used to make calls to Zendesk API.

        Yields:
            TDataItem: Dictionary containing the ticket fields data.
        """
        logger = await bind_temporal_worker_logger(team_id)
        logger.info("Zendesk: getting ticket_fields")

        # get dlt state
        ticket_custom_fields = dlt.current.source_state().setdefault(CUSTOM_FIELDS_STATE_KEY, {})
        # get all custom fields and update state if needed, otherwise just load dicts into tables
        all_fields = list(
            chain.from_iterable(
                zendesk_client.get_pages("/api/v2/ticket_fields.json", "ticket_fields", PaginationType.OFFSET)
            )
        )
        # all_fields = zendesk_client.ticket_fields()
        for field in all_fields:
            yield process_ticket_field(field, ticket_custom_fields)

    ticket_fields_resource = dlt.resource(name="ticket_fields", write_disposition="replace")(ticket_fields_table)

    # Authenticate
    zendesk_client = ZendeskAPIClient(credentials)

    all_endpoints = SUPPORT_ENDPOINTS + SUPPORT_EXTRA_ENDPOINTS

    for endpoint in endpoints:
        # loading base tables
        if endpoint == "ticket_fields":
            yield ticket_fields_resource(zendesk_client=zendesk_client)
        elif endpoint == "ticket_events":
            yield ticket_events(zendesk_client=zendesk_client)
        elif endpoint == "tickets":
            yield ticket_table(zendesk_client=zendesk_client, pivot_fields=pivot_ticket_fields)
        elif endpoint == "ticket_metric_events":
            yield ticket_metric_table(zendesk_client=zendesk_client)
        else:
            # other tables to be loaded
            for resource, endpoint_url, data_key, cursor_paginated in all_endpoints:
                if endpoint == resource:
                    yield dlt.resource(
                        basic_resource,
                        name=resource,
                        write_disposition="replace",
                    )(zendesk_client, endpoint_url, data_key or resource, cursor_paginated, team_id)

                    break


async def basic_resource(
    zendesk_client: ZendeskAPIClient,
    endpoint_url: str,
    data_key: str,
    cursor_paginated: bool,
    team_id: int,
):
    """
    Basic loader for most endpoints offered by Zenpy. Supports pagination. Expects to be called as a DLT Resource.

    Args:
        zendesk_client: The Zendesk API client instance, used to make calls to Zendesk API.
        resource: The Zenpy endpoint to retrieve data from, usually directly linked to a Zendesk API endpoint.
        cursor_paginated: Tells to use CURSOR pagination or OFFSET/no pagination

    Yields:
        TDataItem: Dictionary containing the resource data.
    """

    logger = await bind_temporal_worker_logger(team_id)
    logger.info(f"Zendesk: getting {endpoint_url}")

    pages = zendesk_client.get_pages(
        endpoint_url,
        data_key,
        PaginationType.CURSOR if cursor_paginated else PaginationType.OFFSET,
    )
    yield pages
