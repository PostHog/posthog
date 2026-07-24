from unittest import mock

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ducklake.publish import (
    PUBLISHED_PREFIX,
    delete_stale_publish_versions,
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


class TestDeleteStalePublishVersions(SimpleTestCase):
    # Locks in which snapshot keys survive a prune: deleting the live version would
    # break the warehouse table mid-query, and deleting nothing leaks storage.
    @parameterized.expand(
        [
            ("keeps_listed_versions", {"20260720120000", "20260721120000"}, ["20260719120000"]),
            ("empty_keep_set_deletes_everything", set(), ["20260719120000", "20260720120000", "20260721120000"]),
        ]
    )
    @override_settings(USE_LOCAL_SETUP=False)
    @mock.patch("boto3.client")
    def test_keep_filtering(
        self,
        _name: str,
        keep_versions: set[str],
        expected_deleted_versions: list[str],
        mock_boto_client: mock.MagicMock,
    ) -> None:
        folder = publish_folder(42, "abc123")
        versions = ["20260719120000", "20260720120000", "20260721120000"]
        keys = [f"{PUBLISHED_PREFIX}/{folder}/{version}/part-0.parquet" for version in versions]
        s3 = mock_boto_client.return_value
        s3.get_paginator.return_value.paginate.return_value = [{"Contents": [{"Key": key} for key in keys]}]

        delete_stale_publish_versions("bucket", folder, keep_versions)

        expected_deleted = [
            f"{PUBLISHED_PREFIX}/{folder}/{version}/part-0.parquet" for version in expected_deleted_versions
        ]
        if expected_deleted:
            s3.delete_objects.assert_called_once_with(
                Bucket="bucket", Delete={"Objects": [{"Key": key} for key in expected_deleted]}
            )
        else:
            s3.delete_objects.assert_not_called()
