# ruff: noqa: T201
"""Print the ClickHouse statements setup_test_environment runs, in order, separated by blank lines.

The seed data (exchange rates, channel definitions) stays out: it is megabytes the Node tests never read.
cut_clickhouse_schema.py cuts the output down to what the Node packages reach.
"""

import os
import sys
from pathlib import Path

# The Django project is the repository root, three levels up from this script.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("TEST", "1")
os.environ.setdefault("CLICKHOUSE_DATABASE", "posthog_test")

import django  # noqa: E402

django.setup()

from posthog.clickhouse.schema import (  # noqa: E402
    CREATE_DICTIONARY_QUERIES,
    CREATE_DISTRIBUTED_TABLE_QUERIES,
    CREATE_KAFKA_TABLE_QUERIES,
    CREATE_MERGETREE_TABLE_QUERIES,
    CREATE_MV_TABLE_QUERIES,
    CREATE_VIEW_QUERIES,
)

GROUPS = [
    CREATE_MERGETREE_TABLE_QUERIES,
    CREATE_KAFKA_TABLE_QUERIES,
    CREATE_DISTRIBUTED_TABLE_QUERIES,
    CREATE_MV_TABLE_QUERIES,
    CREATE_VIEW_QUERIES,
    CREATE_DICTIONARY_QUERIES,
]

for queries in GROUPS:
    for query in queries:
        statement = query() if callable(query) else query
        assert isinstance(statement, str)
        print(statement.strip().rstrip(";") + ";\n")
