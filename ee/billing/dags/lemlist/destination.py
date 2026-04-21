"""dlt pipeline factory targeting the Duckgres Postgres endpoint.

Duckgres speaks the Postgres wire protocol, so dlt's first-party ``postgres``
destination works against it. We namespace all Lemlist tables under a dedicated
``lemlist`` schema (``dataset_name``) so they don't collide with other tenants
of the warehouse.
"""

import os

from django.conf import settings

import dlt

from ee.billing.salesforce_enrichment.duckgres_client import DuckgresNotConfiguredError

LEMLIST_DATASET_NAME = "lemlist"
LEMLIST_PIPELINE_NAME = "lemlist"


def build_pipeline(pipeline_name: str = LEMLIST_PIPELINE_NAME) -> dlt.Pipeline:
    """Return a dlt pipeline writing the Lemlist dataset into Duckgres."""
    if not settings.DUCKGRES_PG_URL:
        raise DuckgresNotConfiguredError("DUCKGRES_PG_URL is not set")

    # ``posthog/temporal/data_modeling/run_workflow.py`` sets
    # ``SCHEMA__NAMING=direct`` at module import time so HogQL-derived models
    # preserve casing. dlt reads that env globally and would otherwise apply
    # the ``direct`` convention to our schema too — which uses ``▶`` as the
    # nested-table separator.
    os.environ["SCHEMA__NAMING"] = "snake_case"
    dlt.config[f"sources.{LEMLIST_PIPELINE_NAME}.schema.naming"] = "snake_case"

    pipeline = dlt.pipeline(
        pipeline_name=pipeline_name,
        destination=dlt.destinations.postgres(
            credentials=settings.DUCKGRES_PG_URL,
            # Ducklake rejects PRIMARY KEY / UNIQUE DDL. dlt's merge logic uses
            # the resource-level ``primary_key`` hint to build its MERGE SQL
            create_indexes=False,
            alter_add_multi_column=False,
        ),
        dataset_name=LEMLIST_DATASET_NAME,
        progress="log",
    )
    # Bookkeeping (snapshot_date, load_info) is recorded via Dagster run
    pipeline.config.restore_from_destination = False
    return pipeline
