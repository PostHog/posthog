"""Salesforce source helpers"""

import pendulum

from typing import Optional, Iterable

from simple_salesforce import Salesforce
from dlt.common.typing import TDataItem



def get_records(
    sf: Salesforce,
    sobject: str,
    last_state: Optional[str] = None,
    replication_key: Optional[str] = None,
) -> Iterable[TDataItem]:
    """
    Retrieves records from Salesforce for a specified sObject.

    Args:
        sf (Salesforce): An instance of the Salesforce API client.
        sobject (str): The name of the sObject to retrieve records from.
        last_state (str, optional): The last known state for incremental loading. Defaults to None.
        replication_key (str, optional): The replication key for incremental loading. Defaults to None.

    Yields:
        Dict[TDataItem]: A dictionary representing a record from the Salesforce sObject.
    """

    # Get all fields for the sobject
    desc = getattr(sf, sobject).describe()
    # Salesforce returns compound fields as separate fields, so we need to filter them out
    compound_fields = {
        f["compoundFieldName"]
        for f in desc["fields"]
        if f["compoundFieldName"] is not None
    } - {"Name"}
    # Salesforce returns datetime fields as timestamps, so we need to convert them
    date_fields = {
        f["name"] for f in desc["fields"] if f["type"] in ("datetime",) and f["name"]
    }
    # If no fields are specified, use all fields except compound fields
    fields = [f["name"] for f in desc["fields"] if f["name"] not in compound_fields]

    # Generate a predicate to filter records by the replication key
    predicate, order_by, n_records = "", "", 0
    if replication_key:
        if last_state:
            predicate = f"WHERE {replication_key} > {last_state}"
        order_by = f"ORDER BY {replication_key} ASC"
    query = f"SELECT {', '.join(fields)} FROM {sobject} {predicate} {order_by}"

    # Query all records in batches
    for page in getattr(sf.bulk, sobject).query_all(query, lazy_operation=True):
        for record in page:
            # Strip out the attributes field
            record.pop("attributes", None)
            for field in date_fields:
                # Convert Salesforce timestamps to ISO 8601
                if record.get(field):
                    record[field] = pendulum.from_timestamp(
                        record[field] / 1000,
                    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        yield from page
        n_records += len(page)