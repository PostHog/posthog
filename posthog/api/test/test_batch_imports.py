from posthog.models.batch_imports import BatchImport, ContentType, BatchImportConfigBuilder
from posthog.test.base import APIBaseTest, BaseTest


class TestBatchImportModel(BaseTest):
    def test_batch_import_creation(self):
        batch_import = BatchImport.objects.create(
            team=self.team, created_by_id=self.user.id, import_config={"test": "config"}, secrets={"secret": "value"}
        )

        self.assertEqual(batch_import.team, self.team)
        self.assertEqual(batch_import.created_by_id, self.user.id)
        self.assertEqual(batch_import.status, BatchImport.Status.RUNNING)
        self.assertEqual(batch_import.import_config, {"test": "config"})
        self.assertIsInstance(batch_import.config, BatchImportConfigBuilder)

    def test_content_type_enum(self):
        self.assertEqual(ContentType.MIXPANEL.value, "mixpanel")
        self.assertEqual(ContentType.CAPTURED.value, "captured")
        self.assertEqual(ContentType.AMPLITUDE.value, "amplitude")

        self.assertEqual(ContentType.MIXPANEL.serialize(), {"type": "mixpanel"})


class TestBatchImportConfigBuilder(BaseTest):
    def setUp(self):
        super().setUp()
        self.batch_import = BatchImport(team=self.team)

    def test_json_lines_configuration(self):
        config = self.batch_import.config.json_lines(ContentType.MIXPANEL, skip_blanks=False)

        expected = {"data_format": {"type": "json_lines", "skip_blanks": False, "content": {"type": "mixpanel"}}}
        self.assertEqual(self.batch_import.import_config, expected)
        self.assertIsInstance(config, BatchImportConfigBuilder)

    def test_from_s3_configuration(self):
        self.batch_import.config.from_s3(
            bucket="my-bucket",
            prefix="data/",
            region="us-east-1",
            access_key_id="AKIATEST",
            secret_access_key="secret123",
        )

        expected_config = {
            "source": {
                "type": "s3",
                "bucket": "my-bucket",
                "prefix": "data/",
                "region": "us-east-1",
                "access_key_id_key": "aws_access_key_id",
                "secret_access_key_key": "aws_secret_access_key",
            }
        }
        self.assertEqual(self.batch_import.import_config, expected_config)
        self.assertEqual(self.batch_import.secrets["aws_access_key_id"], "AKIATEST")
        self.assertEqual(self.batch_import.secrets["aws_secret_access_key"], "secret123")

    def test_chained_configuration(self):
        urls = ["http://example.com/data.json"]

        self.batch_import.config.json_lines(ContentType.AMPLITUDE).from_urls(urls).to_kafka("events_topic", 1000, 60)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "source": {"type": "url_list", "urls_key": "urls", "allow_internal_ips": False, "timeout_seconds": 30},
            "sink": {"type": "kafka", "topic": "events_topic", "send_rate": 1000, "transaction_timeout_seconds": 60},
        }
        self.assertEqual(self.batch_import.import_config, expected_config)
        self.assertEqual(self.batch_import.secrets["urls"], urls)


class TestBatchImportAPI(APIBaseTest):
    def test_model_creation_only(self):
        batch_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test", "secret_key": "secret_test"},
            status=BatchImport.Status.COMPLETED,
        )

        self.assertEqual(batch_import.team, self.team)
        self.assertEqual(batch_import.status, BatchImport.Status.COMPLETED)

        found = BatchImport.objects.filter(team=self.team).first()
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.id, batch_import.id)

    def test_cannot_create_multiple_running_imports(self):
        """Test that creating a new batch import fails when there's already a running one for the same team"""
        existing_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test", "secret_key": "secret_test"},
            status=BatchImport.Status.RUNNING,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Cannot create a new batch import", response.json()["error"])
        self.assertIn(str(existing_import.id), response.json()["detail"])

    def test_can_create_import_when_no_running_imports(self):
        """Test that creating a new batch import succeeds when there are no running imports"""
        BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test", "secret_key": "secret_test"},
            status=BatchImport.Status.COMPLETED,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)

    def test_can_create_import_when_other_team_has_running_import(self):
        """Test that creating a new batch import succeeds when another team has a running import"""
        from posthog.models import Team, Organization

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        BatchImport.objects.create(
            team=other_team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test", "secret_key": "secret_test"},
            status=BatchImport.Status.RUNNING,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        self.assertEqual(response.status_code, 201)
