from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ducklake.publish import (
    is_publishable_table,
    publish_folder,
    publish_s3_uri,
    publish_url_pattern,
    reserved_backfill_table_names,
)


class TestPublishHelpers(SimpleTestCase):
    @parameterized.expand(
        [
            ("user_model", "main", "customer_arr", True),
            ("dbt_schema", "dbt_finance", "monthly_arr", True),
            ("imports_schema", "posthog_data_imports_team_1", "stripe_invoice", False),
            ("imports_suffix_schema", "posthog_data_imports_prod", "stripe_invoice", False),
            ("shadow_schema", "shadow_1_models", "model_a", False),
            ("system_schema", "system", "query_log", False),
            ("information_schema", "information_schema", "tables", False),
            ("marker_table", "main", "_posthog_source_batch_duckgres_apply", False),
            ("backfill_scratch", "main", "stripe_invoice__bf_a1b2c3d4", False),
            ("reserved_events", "main", "events_prod", False),
            ("reserved_persons", "main", "persons_prod", False),
        ]
    )
    def test_is_publishable_table(self, _name: str, schema: str, table: str, expected: bool) -> None:
        reserved = reserved_backfill_table_names("prod")
        assert is_publishable_table(schema, table, reserved_table_names=reserved) is expected

    def test_reserved_names_without_suffix_are_shared_tables(self) -> None:
        assert reserved_backfill_table_names(None) == frozenset({"events", "persons"})

    def test_publish_s3_uri_and_folder(self) -> None:
        folder = publish_folder(42, "abc123")
        assert folder == "team_42_publish_abc123"
        assert (
            publish_s3_uri("posthog-duckling-acme-mw-prod-us", folder, "20260720120000")
            == "s3://posthog-duckling-acme-mw-prod-us/__posthog_published/team_42_publish_abc123/20260720120000"
        )

    @override_settings(USE_LOCAL_SETUP=True, OBJECT_STORAGE_ENDPOINT="http://objectstorage:19000")
    def test_publish_url_pattern_local(self) -> None:
        url = publish_url_pattern("ducklake-dev", "us-east-1", "team_42_publish_abc123", "20260720120000")
        assert (
            url
            == "http://objectstorage:19000/ducklake-dev/__posthog_published/team_42_publish_abc123/20260720120000/**.parquet"
        )

    @override_settings(USE_LOCAL_SETUP=False)
    def test_publish_url_pattern_prod(self) -> None:
        url = publish_url_pattern(
            "posthog-duckling-acme-mw-prod-us", "us-east-1", "team_42_publish_abc123", "20260720120000"
        )
        assert url == (
            "https://posthog-duckling-acme-mw-prod-us.s3.us-east-1.amazonaws.com"
            "/__posthog_published/team_42_publish_abc123/20260720120000/**.parquet"
        )
