# ruff: noqa: T201
"""Print the ClickHouse statements setup_test_environment runs, in order, as one SQL file."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("TEST", "1")
os.environ.setdefault("CLICKHOUSE_DATABASE", "posthog_test")

import django  # noqa: E402

django.setup()

from posthog.clickhouse.schema import (  # noqa: E402
    CREATE_DATA_QUERIES,
    CREATE_DICTIONARY_QUERIES,
    CREATE_DISTRIBUTED_TABLE_QUERIES,
    CREATE_KAFKA_TABLE_QUERIES,
    CREATE_MERGETREE_TABLE_QUERIES,
    CREATE_MV_TABLE_QUERIES,
    CREATE_VIEW_QUERIES,
)

GROUPS = [
    ("mergetree", CREATE_MERGETREE_TABLE_QUERIES),
    ("kafka", CREATE_KAFKA_TABLE_QUERIES),
    ("distributed", CREATE_DISTRIBUTED_TABLE_QUERIES),
    ("materialized views", CREATE_MV_TABLE_QUERIES),
    ("views", CREATE_VIEW_QUERIES),
    ("dictionaries", CREATE_DICTIONARY_QUERIES),
    ("data", CREATE_DATA_QUERIES()),
]

for name, queries in GROUPS:
    print(f"-- {name}")
    for query in queries:
        statement = (query() if callable(query) else query).strip().rstrip(";")
        print(statement + ";\n")
