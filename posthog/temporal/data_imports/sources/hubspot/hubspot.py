"""
This is a module that provides a DLT source to retrieve data from multiple endpoints of the HubSpot API using a specified API key. The retrieved data is returned as a tuple of Dlt resources, one for each endpoint.

The source retrieves data from the following endpoints:
- CRM Companies
- CRM Contacts
- CRM Deals
- CRM Tickets
- CRM Quotes
- Web Analytics Events

For each endpoint, a resource and transformer function are defined to retrieve data and transform it to a common format.
The resource functions yield the raw data retrieved from the API, while the transformer functions are used to retrieve
additional information from the Web Analytics Events endpoint.

The source also supports enabling Web Analytics Events for each endpoint by setting the corresponding enable flag to True.

Example:
To retrieve data from all endpoints, use the following code:

python

>>> resources = hubspot(api_key="hubspot_access_code")
"""

import urllib.parse
from collections.abc import Iterator, Sequence
from typing import Any, Literal

from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse

from .helpers import _get_property_names, fetch_data, fetch_property_history
from .settings import CRM_OBJECT_ENDPOINTS, DEFAULT_PROPS, OBJECT_TYPE_SINGULAR

THubspotObjectType = Literal["company", "contact", "deal", "ticket", "quote"]

PROPERTY_LENGTH_LIMIT = 16_000  # This has been empirically determined to be the rough limit for the Hubspot API


def hubspot(
    api_key: str,
    refresh_token: str,
    logger: FilteringBoundLogger,
    endpoints: Sequence[str] = ("companies", "contacts", "deals", "tickets", "quotes"),
    include_history: bool = False,
) -> list[SourceResponse]:
    """
    A source that retrieves data from the HubSpot API using the specified API key.

    This function retrieves data for several HubSpot API endpoints,
    including companies, contacts, deals, tickets and web
    analytics events. It returns a list of SourceResponse objects, one for
    each endpoint.

    Args:
        api_key: The API key used to authenticate with the HubSpot API.
        refresh_token: OAuth refresh token for refreshing the access token.
        logger: Logger for this source.
        endpoints: List of endpoints to fetch data from.
        include_history: Whether to load history of property changes along with entities.
            The history entries are loaded to separate tables.

    Returns:
        list[SourceResponse]: Source responses, one for each HubSpot API endpoint.

    Notes:
        This function uses the `fetch_data` function to retrieve data from the
        HubSpot CRM API. The API key is passed to `fetch_data` as the
        `api_key` argument.
    """

    responses = []
    for endpoint in endpoints:
        responses.append(
            SourceResponse(
                name=endpoint,
                items=lambda obj_type: str = OBJECT_TYPE_SINGULAR[endpoint], props: list[str] = DEFAULT_PROPS[endpoint]: crm_objects(  # type: ignore[misc]
                    object_type=obj_type,
                    api_key=api_key,
                    refresh_token=refresh_token,
                    include_history=include_history,
                    props=props,
                    include_custom_props=True,
                    logger=logger,
                ),
                primary_keys=["id"],
                column_hints=None,
                partition_count=None,
            )
        )
    return responses


def _get_properties_str(
    props: Sequence[str],
    api_key: str,
    refresh_token: str,
    object_type: str,
    logger: FilteringBoundLogger,
    include_custom_props: bool = True,
) -> str:
    """Builds a string of properties to be requested from the Hubspot API."""
    props = list(props)
    if include_custom_props:
        all_props = _get_property_names(api_key, refresh_token, object_type)
        custom_props = [prop for prop in all_props if not prop.startswith("hs_")]
        props = props + [c for c in custom_props if c not in props]

    props_str = ""
    for i, prop in enumerate(props):
        len_url_encoded_props = len(urllib.parse.quote(prop if not props_str else f"{props_str},{prop}"))
        if len_url_encoded_props > PROPERTY_LENGTH_LIMIT:
            logger.warning(
                "Your request to Hubspot is too long to process. "
                f"Therefore, only the first {i} of {len(props)} custom properties will be requested."
            )
            break
        if not props_str:
            props_str = prop
        else:
            props_str = f"{props_str},{prop}"

    return props_str


def crm_objects(
    object_type: str,
    api_key: str,
    refresh_token: str,
    include_history: bool,
    props: Sequence[str],
    logger: FilteringBoundLogger,
    include_custom_props: bool = True,
) -> Iterator[list[dict[str, Any]]]:
    """Building blocks for CRM resources."""
    props_str = _get_properties_str(
        props=props,
        api_key=api_key,
        refresh_token=refresh_token,
        object_type=object_type,
        include_custom_props=include_custom_props,
        logger=logger,
    )

    params = {"properties": props_str, "limit": 100}

    yield from fetch_data(CRM_OBJECT_ENDPOINTS[object_type], api_key, refresh_token, params=params)
    if include_history:
        # Get history separately, as requesting both all properties and history together
        # is likely to hit hubspot's URL length limit
        # Note: History data is yielded directly; table naming is handled by the consumer
        yield from fetch_property_history(
            CRM_OBJECT_ENDPOINTS[object_type],
            api_key,
            props_str,
        )
