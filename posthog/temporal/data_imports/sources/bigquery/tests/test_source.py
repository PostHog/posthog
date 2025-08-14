from unittest import mock

from posthog.temporal.data_imports.sources.bigquery.source import BigQuerySource


def test_bigquery_get_schemas():
    with mock.patch(
        "posthog.temporal.data_imports.sources.bigquery.source.get_bigquery_schemas", return_value={"table": []}
    ):
        source_cls = BigQuerySource()
        schemas = source_cls.get_schemas(mock.ANY, 1)
        assert len(schemas) == 1
        assert schemas[0].name == "table"


def test_bigquery_get_schemas_with_existing_destination_tables():
    with mock.patch(
        "posthog.temporal.data_imports.sources.bigquery.source.get_bigquery_schemas",
        return_value={"table": [], "__posthog_import_0000_0000": []},
    ):
        source_cls = BigQuerySource()
        schemas = source_cls.get_schemas(mock.ANY, 1)
        assert len(schemas) == 1
        assert schemas[0].name == "table"
