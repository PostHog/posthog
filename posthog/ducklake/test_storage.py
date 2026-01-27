from parameterized import parameterized

from posthog.ducklake.storage import DuckLakeStorageConfig, normalize_endpoint


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
