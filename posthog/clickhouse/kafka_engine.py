# Note for the vary: these engine definitions (and many table definitions) are not in sync with cloud!

from django.conf import settings

STORAGE_POLICY = lambda: "SETTINGS storage_policy = 'hot_to_cold'" if settings.CLICKHOUSE_ENABLE_STORAGE_POLICY else ""

KAFKA_ENGINE = "Kafka('{kafka_host}', '{topic}', '{group}', '{serialization}')"
KAFKA_NAMED_COLLECTION_ENGINE = "Kafka({named_collection_name}, kafka_topic_list = '{topic}', kafka_group_name = '{group}', kafka_format = '{serialization}')"


# The kafka_engine automatically adds these columns to the kafka tables. We use
# this string to add them to the other tables as well.
KAFKA_COLUMNS = """
, _timestamp DateTime
, _offset UInt64
"""


def kafka_engine(
    topic: str,
    kafka_host: str | None = None,
    group="group1",
    serialization="JSONEachRow",
    use_named_collection: bool = True,
    named_collection: str | None = None,
) -> str:
    if use_named_collection:
        assert kafka_host is None, "Can't set kafka_host when using named collection"
        # Use explicit named_collection if provided, otherwise default to MSK
        collection_name = named_collection or settings.CLICKHOUSE_KAFKA_NAMED_COLLECTION
        return KAFKA_NAMED_COLLECTION_ENGINE.format(
            named_collection_name=collection_name,
            topic=topic,
            group=group,
            serialization=serialization,
        )

    if kafka_host is None:
        raise ValueError("kafka_host is required when use_named_collection=False")
    return KAFKA_ENGINE.format(topic=topic, kafka_host=kafka_host, group=group, serialization=serialization)


def trim_quotes_expr(expr: str) -> str:
    return f"replaceRegexpAll({expr}, '^\"|\"$', '')"


def json_extract_trim_quotes(*args: str) -> str:
    """Build a ClickHouse SQL expression that extracts a JSON value as a trimmed string.

    Takes the same arguments as JSONExtractRaw (field, key1, key2, ...) and wraps the
    result to: strip surrounding quotes, convert empty string and literal 'null' to NULL.

    Three code paths must produce byte-identical output for the same input:
    - HogQL printer's JSON fallback (``_unsafe_json_extract_trim_quotes``)
    - SQL backfill mutation (``_generate_property_extraction_sql``)
    - Plugin-server live ingest (``jsonExtractRawAndTrimQuotes`` in create-event.ts)

    This function is the single source of truth for the SQL shape so the Python
    paths can't drift from each other. The TypeScript path is covered by the
    shared coercion fixture in ``coercion_fixtures.json``.
    """
    return f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw({', '.join(args)}), ''), 'null'), '^\"|\"$', '')"
