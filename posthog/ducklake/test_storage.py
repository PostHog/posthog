from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.ducklake.storage import (
    _DELTA_LOG_VERSION_RE,
    DuckLakeStorageConfig,
    _collect_delta_log_keys,
    normalize_endpoint,
)


class TestNormalizeEndpoint:
    @parameterized.expand(
        [
            ("http://localhost:19000", ("localhost:19000", False)),
            ("https://s3.amazonaws.com", ("s3.amazonaws.com", True)),
            ("http://minio:9000/", ("minio:9000", False)),
            ("https://storage.example.com/", ("storage.example.com", True)),
            ("localhost:19000", ("localhost:19000", False)),
            ("", ("", True)),
            ("  http://localhost:9000  ", ("localhost:9000", False)),
        ]
    )
    def test_normalize_endpoint(self, input_endpoint, expected):
        assert normalize_endpoint(input_endpoint) == expected


class TestDuckLakeStorageConfigLocalSetup:
    def test_from_runtime_local_setup_with_endpoint(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_S3_ACCESS_KEY", "test_access_key")
        monkeypatch.setenv("DUCKLAKE_S3_SECRET_KEY", "test_secret_key")
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "us-west-2")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": True,
                "OBJECT_STORAGE_ENDPOINT": "http://localhost:19000",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)

        config = DuckLakeStorageConfig.from_runtime()

        assert config.access_key == "test_access_key"
        assert config.secret_key == "test_secret_key"
        assert config.region == "us-west-2"
        assert config.endpoint == "localhost:19000"
        assert config.use_ssl is False
        assert config.url_style == "path"
        assert config.is_local is True

    def test_from_runtime_local_setup_https_endpoint(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_S3_ACCESS_KEY", "test_key")
        monkeypatch.setenv("DUCKLAKE_S3_SECRET_KEY", "test_secret")
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "eu-west-1")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": True,
                "OBJECT_STORAGE_ENDPOINT": "https://s3.eu-west-1.amazonaws.com",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)

        config = DuckLakeStorageConfig.from_runtime()

        assert config.endpoint == "s3.eu-west-1.amazonaws.com"
        assert config.use_ssl is True

    def test_to_duckdb_secret_sql_local_setup(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_S3_ACCESS_KEY", "test_key")
        monkeypatch.setenv("DUCKLAKE_S3_SECRET_KEY", "test_secret")
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "us-east-1")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": True,
                "OBJECT_STORAGE_ENDPOINT": "http://localhost:19000",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)

        config = DuckLakeStorageConfig.from_runtime()
        sql = config.to_duckdb_secret_sql()

        assert "TYPE S3" in sql
        assert "KEY_ID 'test_key'" in sql
        assert "SECRET 'test_secret'" in sql
        assert "REGION 'us-east-1'" in sql
        assert "ENDPOINT 'localhost:19000'" in sql
        assert "USE_SSL false" in sql
        assert "URL_STYLE 'path'" in sql
        assert "PROVIDER CREDENTIAL_CHAIN" not in sql

    def test_to_deltalake_options_local_setup(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_S3_ACCESS_KEY", "ak123")
        monkeypatch.setenv("DUCKLAKE_S3_SECRET_KEY", "sk456")
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "us-west-1")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": True,
                "OBJECT_STORAGE_ENDPOINT": "http://minio:9000",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)

        config = DuckLakeStorageConfig.from_runtime()
        options = config.to_deltalake_options()

        assert options["aws_access_key_id"] == "ak123"
        assert options["aws_secret_access_key"] == "sk456"
        assert options["region_name"] == "us-west-1"
        assert options["AWS_DEFAULT_REGION"] == "us-west-1"
        assert options["endpoint_url"] == "http://minio:9000"
        assert options["AWS_ALLOW_HTTP"] == "true"
        assert options["AWS_S3_ALLOW_UNSAFE_RENAME"] == "true"


class TestDuckLakeStorageConfigProduction:
    def test_from_runtime_production_irsa(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "us-east-1")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": False,
                "OBJECT_STORAGE_ENDPOINT": "",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)

        config = DuckLakeStorageConfig.from_runtime()

        assert config.access_key == ""
        assert config.secret_key == ""
        assert config.region == "us-east-1"
        assert config.endpoint == ""
        assert config.use_ssl is True
        assert config.url_style == "path"
        assert config.is_local is False

    def test_to_duckdb_secret_sql_production_irsa(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "eu-central-1")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": False,
                "OBJECT_STORAGE_ENDPOINT": "",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)
        monkeypatch.setattr(
            "posthog.ducklake.storage._get_boto3_credentials",
            lambda: ("ASIAACCESSKEY", "secretkey123", "sessiontoken456"),
        )

        config = DuckLakeStorageConfig.from_runtime()
        sql = config.to_duckdb_secret_sql()

        assert "TYPE S3" in sql
        assert "KEY_ID 'ASIAACCESSKEY'" in sql
        assert "SECRET 'secretkey123'" in sql
        assert "SESSION_TOKEN 'sessiontoken456'" in sql
        assert "REGION 'eu-central-1'" in sql
        assert "PROVIDER CREDENTIAL_CHAIN" not in sql
        assert "ENDPOINT '" not in sql

    def test_to_duckdb_secret_sql_production_no_session_token(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "us-east-1")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": False,
                "OBJECT_STORAGE_ENDPOINT": "",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)
        monkeypatch.setattr(
            "posthog.ducklake.storage._get_boto3_credentials",
            lambda: ("AKIAACCESSKEY", "secretkey789", None),
        )

        config = DuckLakeStorageConfig.from_runtime()
        sql = config.to_duckdb_secret_sql()

        assert "TYPE S3" in sql
        assert "KEY_ID 'AKIAACCESSKEY'" in sql
        assert "SECRET 'secretkey789'" in sql
        assert "SESSION_TOKEN" not in sql
        assert "REGION 'us-east-1'" in sql

    def test_to_deltalake_options_production_irsa(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "us-west-2")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": False,
                "OBJECT_STORAGE_ENDPOINT": "",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)

        config = DuckLakeStorageConfig.from_runtime()
        options = config.to_deltalake_options()

        assert options["AWS_DEFAULT_REGION"] == "us-west-2"
        assert options["AWS_S3_ALLOW_UNSAFE_RENAME"] == "true"
        assert "aws_access_key_id" not in options
        assert "aws_secret_access_key" not in options
        assert "endpoint_url" not in options


class TestDuckLakeStorageConfigEdgeCases:
    def test_empty_values_filtered_from_deltalake_options(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_S3_ACCESS_KEY", "")
        monkeypatch.setenv("DUCKLAKE_S3_SECRET_KEY", "")
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": True,
                "OBJECT_STORAGE_ENDPOINT": "",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)

        config = DuckLakeStorageConfig.from_runtime()
        options = config.to_deltalake_options()

        assert "aws_access_key_id" not in options
        assert "aws_secret_access_key" not in options
        assert "endpoint_url" not in options
        assert options.get("AWS_S3_ALLOW_UNSAFE_RENAME") == "true"

    def test_special_characters_escaped_in_sql(self):
        config = DuckLakeStorageConfig(
            access_key="key'with'quotes",
            secret_key="secret'value",
            region="us-east-1",
            endpoint="localhost:9000",
            use_ssl=False,
            url_style="path",
            is_local=True,
        )
        sql = config.to_duckdb_secret_sql()

        assert "key''with''quotes" in sql
        assert "secret''value" in sql

    def test_explicit_use_local_setup_override(self, monkeypatch):
        monkeypatch.setenv("DUCKLAKE_S3_ACCESS_KEY", "override_key")
        monkeypatch.setenv("DUCKLAKE_S3_SECRET_KEY", "override_secret")
        monkeypatch.setenv("DUCKLAKE_BUCKET_REGION", "us-east-1")

        mock_settings = type(
            "Settings",
            (),
            {
                "USE_LOCAL_SETUP": False,
                "OBJECT_STORAGE_ENDPOINT": "http://local:9000",
            },
        )()
        monkeypatch.setattr("posthog.ducklake.storage._get_django_settings", lambda: mock_settings)

        config = DuckLakeStorageConfig.from_runtime(use_local_setup=True)

        assert config.access_key == "override_key"
        assert config.secret_key == "override_secret"
        assert config.is_local is True


class TestCrossAccountDestination:
    def test_destination_attributes(self):
        from posthog.ducklake.storage import CrossAccountDestination

        dest = CrossAccountDestination(
            role_arn="arn:aws:iam::123456789012:role/MyRole",
            external_id="ext-id-123",
            bucket_name="my-customer-bucket",
            region="us-west-2",
        )
        assert dest.role_arn == "arn:aws:iam::123456789012:role/MyRole"
        assert dest.external_id == "ext-id-123"
        assert dest.bucket_name == "my-customer-bucket"
        assert dest.region == "us-west-2"

    def test_optional_fields_default_to_none(self):
        from posthog.ducklake.storage import CrossAccountDestination

        dest = CrossAccountDestination(
            role_arn="arn:aws:iam::123456789012:role/MyRole",
            bucket_name="bucket",
        )
        assert dest.external_id is None
        assert dest.region is None


class TestDuckLakeCatalogToCrossAccountDestination:
    def test_converts_to_cross_account_destination(self):
        from unittest.mock import MagicMock

        from posthog.ducklake.models import DuckLakeCatalog

        # Create a mock catalog with the required attributes
        catalog = MagicMock(spec=DuckLakeCatalog)
        catalog.cross_account_role_arn = "arn:aws:iam::222222222222:role/CustomerRole"
        catalog.cross_account_external_id = "external-id-456"
        catalog.bucket = "customer-bucket"
        catalog.bucket_region = "eu-west-1"

        # Call the real method on the mock
        dest = DuckLakeCatalog.to_cross_account_destination(catalog)

        assert dest.role_arn == "arn:aws:iam::222222222222:role/CustomerRole"
        assert dest.external_id == "external-id-456"
        assert dest.bucket_name == "customer-bucket"
        assert dest.region == "eu-west-1"

    def test_none_region_handled(self):
        from unittest.mock import MagicMock

        from posthog.ducklake.models import DuckLakeCatalog

        catalog = MagicMock(spec=DuckLakeCatalog)
        catalog.cross_account_role_arn = "arn:aws:iam::111:role/Role"
        catalog.cross_account_external_id = "ext-id"
        catalog.bucket = "bucket"
        catalog.bucket_region = ""  # Empty string should become None

        dest = DuckLakeCatalog.to_cross_account_destination(catalog)

        assert dest.region is None


def _make_s3_page(keys: list[str]) -> list[dict]:
    return [{"Contents": [{"Key": k} for k in keys]}]


def _mock_paginator(pages: list[dict]):
    paginator = MagicMock()
    paginator.paginate.return_value = pages
    return paginator


class TestCollectDeltaLogKeys:
    @parameterized.expand(
        [
            (
                "includes_commit_and_checkpoint_up_to_version",
                [
                    "data/table/_delta_log/00000000000000000000.json",
                    "data/table/_delta_log/00000000000000000001.json",
                    "data/table/_delta_log/00000000000000000002.json",
                    "data/table/_delta_log/00000000000000000003.json",
                    "data/table/_delta_log/00000000000000000002.checkpoint.parquet",
                ],
                2,
                [
                    "data/table/_delta_log/00000000000000000000.json",
                    "data/table/_delta_log/00000000000000000001.json",
                    "data/table/_delta_log/00000000000000000002.json",
                    "data/table/_delta_log/00000000000000000002.checkpoint.parquet",
                ],
            ),
            (
                "excludes_log_files_above_max_version",
                [
                    "data/table/_delta_log/00000000000000000000.json",
                    "data/table/_delta_log/00000000000000000001.json",
                    "data/table/_delta_log/00000000000000000002.json",
                ],
                0,
                [
                    "data/table/_delta_log/00000000000000000000.json",
                ],
            ),
            (
                "handles_multi_part_checkpoint",
                [
                    "data/table/_delta_log/00000000000000000010.checkpoint.0000000001.0000000002.parquet",
                    "data/table/_delta_log/00000000000000000010.checkpoint.0000000002.0000000002.parquet",
                    "data/table/_delta_log/00000000000000000011.json",
                ],
                10,
                [
                    "data/table/_delta_log/00000000000000000010.checkpoint.0000000001.0000000002.parquet",
                    "data/table/_delta_log/00000000000000000010.checkpoint.0000000002.0000000002.parquet",
                ],
            ),
            (
                "version_zero_edge_case",
                [
                    "data/table/_delta_log/00000000000000000000.json",
                    "data/table/_delta_log/00000000000000000001.json",
                    "data/table/_delta_log/_last_checkpoint",
                ],
                0,
                [
                    "data/table/_delta_log/00000000000000000000.json",
                ],
            ),
            (
                "empty_log_directory",
                [],
                5,
                [],
            ),
        ]
    )
    def test_collect_delta_log_keys(self, _name, s3_keys, max_version, expected):
        s3 = MagicMock()
        s3.get_paginator.return_value = _mock_paginator(_make_s3_page(s3_keys))

        result = _collect_delta_log_keys(s3, "src-bucket", "data/table/", max_version)
        assert result == expected


class TestDeltaLogVersionRegex:
    @parameterized.expand(
        [
            ("00000000000000000000.json", "00000000000000000000", 0),
            ("00000000000000000042.checkpoint.parquet", "00000000000000000042", 42),
            ("00000000000000000010.checkpoint.0000000001.0000000002.parquet", "00000000000000000010", 10),
        ]
    )
    def test_matches_valid_filenames(self, filename, expected_group, expected_version):
        m = _DELTA_LOG_VERSION_RE.match(filename)
        assert m is not None
        assert m.group(1) == expected_group
        assert int(m.group(1)) == expected_version

    @parameterized.expand(
        [
            ("_last_checkpoint",),
            (".hidden_file",),
        ]
    )
    def test_does_not_match_non_versioned_files(self, filename):
        assert _DELTA_LOG_VERSION_RE.match(filename) is None


class TestGetDeltaSnapshotFiles:
    def test_returns_version_and_data_keys(self, monkeypatch):
        import sys
        import types

        mock_dt = MagicMock()
        mock_dt.version.return_value = 3
        mock_dt.file_uris.return_value = [
            "s3://customer-bucket/data/table/part-00000.parquet",
            "s3://customer-bucket/data/table/part-00001.parquet",
        ]

        mock_delta_table_cls = MagicMock(return_value=mock_dt)
        mock_deltalake = types.ModuleType("deltalake")
        mock_deltalake.DeltaTable = mock_delta_table_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "deltalake", mock_deltalake)
        monkeypatch.setattr("posthog.ducklake.storage.get_deltalake_storage_options", lambda: {"key": "val"})

        from posthog.ducklake.storage import _get_delta_snapshot_files

        version, keys = _get_delta_snapshot_files("s3://customer-bucket/data/table")
        assert version == 3
        assert keys == ["data/table/part-00000.parquet", "data/table/part-00001.parquet"]

        mock_delta_table_cls.assert_called_once_with(
            table_uri="s3://customer-bucket/data/table",
            storage_options={"key": "val"},
        )


class TestStageDeltaTable:
    @patch("boto3.client")
    def test_copies_only_pinned_version_files(self, mock_boto3_client, monkeypatch):
        monkeypatch.setattr(
            "posthog.ducklake.storage._get_delta_snapshot_files",
            lambda source_uri: (
                2,
                ["data/table/part-00000.parquet", "data/table/part-00001.parquet"],
            ),
        )
        monkeypatch.setattr(
            "posthog.ducklake.storage._get_cross_account_credentials",
            lambda role_arn, external_id=None: ("ak", "sk", "tok"),
        )

        mock_s3 = MagicMock()
        mock_s3.get_paginator.return_value = _mock_paginator(
            _make_s3_page(
                [
                    "data/table/_delta_log/00000000000000000000.json",
                    "data/table/_delta_log/00000000000000000001.json",
                    "data/table/_delta_log/00000000000000000002.json",
                    "data/table/_delta_log/00000000000000000003.json",
                    "data/table/_delta_log/_last_checkpoint",
                ]
            )
        )
        mock_boto3_client.return_value = mock_s3

        from posthog.ducklake.storage import stage_delta_table

        result = stage_delta_table(
            source_uri="s3://customer-bucket/data/table",
            catalog_bucket="catalog-bucket",
            role_arn="arn:aws:iam::123:role/Role",
        )

        assert result == "s3://catalog-bucket/__posthog_staging/data/table"

        copied_keys = sorted(call.kwargs["Key"] for call in mock_s3.copy_object.call_args_list)
        expected = sorted(
            [
                "__posthog_staging/data/table/part-00000.parquet",
                "__posthog_staging/data/table/part-00001.parquet",
                "__posthog_staging/data/table/_delta_log/00000000000000000000.json",
                "__posthog_staging/data/table/_delta_log/00000000000000000001.json",
                "__posthog_staging/data/table/_delta_log/00000000000000000002.json",
            ]
        )
        assert copied_keys == expected

        # version 3 log entry must NOT have been copied
        all_copied = [call.kwargs["Key"] for call in mock_s3.copy_object.call_args_list]
        assert "__posthog_staging/data/table/_delta_log/00000000000000000003.json" not in all_copied
