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

from typing import Literal
from collections.abc import Sequence, Iterator, Iterable

import dlt
from dlt.common.typing import TDataItems
from dlt.sources import DltResource

from .helpers import (
    fetch_data,
    _get_property_names,
    fetch_property_history,
)
from .settings import (
    ALL,
    CRM_OBJECT_ENDPOINTS,
    DEFAULT_PROPS,
    OBJECT_TYPE_PLURAL,
    OBJECT_TYPE_SINGULAR,
)

THubspotObjectType = Literal["company", "contact", "deal", "ticket", "quote"]


@dlt.source(name="hubspot")
def hubspot(
    api_key: str,
    refresh_token: str,
    endpoints: Sequence[str] = ("companies", "contacts", "deals", "tickets", "quotes"),
    include_history: bool = False,
) -> Iterable[DltResource]:
    """
    A DLT source that retrieves data from the HubSpot API using the
    specified API key.

    This function retrieves data for several HubSpot API endpoints,
    including companies, contacts, deals, tickets and web
    analytics events. It returns a tuple of Dlt resources, one for
    each endpoint.

    Args:
        api_key (Optional[str]):
            The API key used to authenticate with the HubSpot API. Defaults
            to dlt.secrets.value.
        include_history (Optional[bool]):
            Whether to load history of property changes along with entities.
            The history entries are loaded to separate tables.

    Returns:
        Sequence[DltResource]: Dlt resources, one for each HubSpot API endpoint.

    Notes:
        This function uses the `fetch_data` function to retrieve data from the
        HubSpot CRM API. The API key is passed to `fetch_data` as the
        `api_key` argument.
    """

    for endpoint in endpoints:
        yield dlt.resource(
            crm_objects,
            name=endpoint,
            write_disposition="replace",
            table_format="delta",
        )(
            object_type=OBJECT_TYPE_SINGULAR[endpoint],
            api_key=api_key,
            refresh_token=refresh_token,
            include_history=include_history,
            props=DEFAULT_PROPS[endpoint],
            include_custom_props=True,
        )


def crm_objects(
    object_type: str,
    api_key: str,
    refresh_token: str,
    include_history: bool,
    props: Sequence[str],
    include_custom_props: bool = True,
) -> Iterator[TDataItems]:
    """Building blocks for CRM resources."""
    if props == ALL:
        props = list(_get_property_names(api_key, refresh_token, object_type))

    if include_custom_props:
        all_props = _get_property_names(api_key, refresh_token, object_type)
        custom_props = [prop for prop in all_props if not prop.startswith("hs_")]
        props = props + custom_props  # type: ignore

    props = ",".join(sorted(set(props)))
    PROP_LENGTH_LIMIT = 20000

    if len(props) > PROP_LENGTH_LIMIT:
        raise ValueError(
            "Your request to Hubspot is too long to process. "
            f"Maximum allowed query length is {PROP_LENGTH_LIMIT} symbols, while "
            f"your list of properties `{props[:200]}`... is {len(props)} "
            "symbols long. Use the `props` argument of the resource to "
            "set the list of properties to extract from the endpoint."
        )

    params = {"properties": props, "limit": 100}

    yield from fetch_data(CRM_OBJECT_ENDPOINTS[object_type], api_key, refresh_token, params=params)
    if include_history:
        # Get history separately, as requesting both all properties and history together
        # is likely to hit hubspot's URL length limit
        for history_entries in fetch_property_history(
            CRM_OBJECT_ENDPOINTS[object_type],
            api_key,
            props,
        ):
            yield dlt.mark.with_table_name(
                history_entries,
                OBJECT_TYPE_PLURAL[object_type] + "_property_history",
            )
