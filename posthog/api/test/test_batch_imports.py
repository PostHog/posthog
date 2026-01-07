from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, BaseTest

from parameterized import parameterized

from posthog.models.batch_imports import BatchImport, BatchImportConfigBuilder, ContentType


class TestBatchImportModel(BaseTest):
    def test_batch_import_creation(self):
        batch_import = BatchImport.objects.create(
            team=self.team, created_by_id=self.user.id, import_config={"test": "config"}, secrets={"secret": "value"}
        )

        assert batch_import.team == self.team
        assert batch_import.created_by_id == self.user.id
        assert batch_import.status == BatchImport.Status.RUNNING
        assert batch_import.import_config == {"test": "config"}
        assert isinstance(batch_import.config, BatchImportConfigBuilder)

    def test_content_type_enum(self):
        assert ContentType.MIXPANEL.value == "mixpanel"
        assert ContentType.CAPTURED.value == "captured"
        assert ContentType.AMPLITUDE.value == "amplitude"

        assert ContentType.MIXPANEL.serialize() == {"type": "mixpanel"}


class TestBatchImportConfigBuilder(BaseTest):
    def setUp(self):
        super().setUp()
        self.batch_import = BatchImport(team=self.team)

    def test_json_lines_configuration(self):
        config = self.batch_import.config.json_lines(ContentType.MIXPANEL, skip_blanks=False)

        expected = {"data_format": {"type": "json_lines", "skip_blanks": False, "content": {"type": "mixpanel"}}}
        assert self.batch_import.import_config == expected
        assert isinstance(config, BatchImportConfigBuilder)

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
        assert self.batch_import.import_config == expected_config
        assert self.batch_import.secrets["aws_access_key_id"] == "AKIATEST"
        assert self.batch_import.secrets["aws_secret_access_key"] == "secret123"

    def test_chained_configuration(self):
        urls = ["http://example.com/data.json"]

        self.batch_import.config.json_lines(ContentType.AMPLITUDE).from_urls(urls).to_kafka("events_topic", 1000, 60)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "source": {"type": "url_list", "urls_key": "urls", "allow_internal_ips": False, "timeout_seconds": 30},
            "sink": {"type": "kafka", "topic": "events_topic", "send_rate": 1000, "transaction_timeout_seconds": 60},
        }
        assert self.batch_import.import_config == expected_config
        assert self.batch_import.secrets["urls"] == urls

    def test_with_generate_identify_events_configuration(self):
        """Test that generate_identify_events is added as a top-level config field"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_generate_identify_events(True)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "generate_identify_events": True,
        }
        assert self.batch_import.import_config == expected_config

    def test_config_builder_does_not_include_amplitude_fields_by_default(self):
        """Test that config builder doesn't include Amplitude-specific fields unless explicitly set"""
        self.batch_import.config.json_lines(ContentType.MIXPANEL).from_urls(["http://example.com"])

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "mixpanel"}},
            "source": {"type": "url_list", "urls_key": "urls", "allow_internal_ips": False, "timeout_seconds": 30},
        }
        assert self.batch_import.import_config == expected_config
        assert "import_events" not in self.batch_import.import_config
        assert "generate_identify_events" not in self.batch_import.import_config
        assert "generate_group_identify_events" not in self.batch_import.import_config

    def test_with_import_events_configuration(self):
        """Test that import_events is added as a top-level config field"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_import_events(False)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "import_events": False,
        }
        assert self.batch_import.import_config == expected_config

    def test_with_both_amplitude_options(self):
        """Test that both import_events and generate_identify_events can be set together"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_import_events(
            True
        ).with_generate_identify_events(True)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "import_events": True,
            "generate_identify_events": True,
        }
        assert self.batch_import.import_config == expected_config

    def test_with_generate_group_identify_events_configuration(self):
        """Test that generate_group_identify_events is added as a top-level config field"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_generate_group_identify_events(True)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "generate_group_identify_events": True,
        }
        assert self.batch_import.import_config == expected_config

    def test_with_all_amplitude_options(self):
        """Test that all Amplitude-specific options can be set together"""
        self.batch_import.config.json_lines(ContentType.AMPLITUDE).with_import_events(
            True
        ).with_generate_identify_events(False).with_generate_group_identify_events(True)

        expected_config = {
            "data_format": {"type": "json_lines", "skip_blanks": True, "content": {"type": "amplitude"}},
            "import_events": True,
            "generate_identify_events": False,
            "generate_group_identify_events": True,
        }
        assert self.batch_import.import_config == expected_config


class TestBatchImportAPI(APIBaseTest):
    def test_model_creation_only(self):
        batch_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test", "secret_key": "secret_test"},
            status=BatchImport.Status.COMPLETED,
        )

        assert batch_import.team == self.team
        assert batch_import.status == BatchImport.Status.COMPLETED

        found = BatchImport.objects.filter(team=self.team).first()
        assert found is not None
        assert found is not None
        assert found.id == batch_import.id

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

        assert response.status_code == 400
        assert "Cannot create a new batch import" in response.json()["error"]
        assert str(existing_import.id) in response.json()["detail"]

    def test_amplitude_validation_requires_at_least_one_option(self):
        """Test that Amplitude migrations require at least one of import_events or generate_identify_events"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "import_events": False,
                "generate_identify_events": False,
            },
        )

        assert response.status_code == 400
        response_data = response.json()
        assert (
            "At least one of 'Import events' or 'Generate identify events' must be enabled for Amplitude migrations"
            in str(response_data)
        ), f"Expected validation error message not found in response: {response_data}"

    def test_mixpanel_migration_does_not_include_amplitude_specific_fields(self):
        """Test that Mixpanel migrations don't include Amplitude-specific fields in config"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "mixpanel",
                "content_type": "mixpanel",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        assert response.status_code == 201

        # Get the created batch import and check its config
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        assert "import_events" not in batch_import.import_config
        assert "generate_identify_events" not in batch_import.import_config
        assert "generate_group_identify_events" not in batch_import.import_config

    def test_amplitude_migration_includes_amplitude_specific_fields(self):
        """Test that Amplitude migrations include import_events and generate_identify_events in config"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "import_events": True,
                "generate_identify_events": False,
            },
        )

        assert response.status_code == 201

        # Get the created batch import and check its config
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        assert "import_events" in batch_import.import_config
        assert "generate_identify_events" in batch_import.import_config
        assert batch_import.import_config["import_events"]
        assert not batch_import.import_config["generate_identify_events"]

    def test_amplitude_migration_with_group_identify_events(self):
        """Test that Amplitude migrations can include generate_group_identify_events in config"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "import_events": True,
                "generate_identify_events": True,
                "generate_group_identify_events": True,
            },
        )

        assert response.status_code == 201

        # Get the created batch import and check its config
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        assert "import_events" in batch_import.import_config
        assert "generate_identify_events" in batch_import.import_config
        assert "generate_group_identify_events" in batch_import.import_config
        assert batch_import.import_config["import_events"]
        assert batch_import.import_config["generate_identify_events"]
        assert batch_import.import_config["generate_group_identify_events"]

    def test_amplitude_migration_group_identify_events_defaults_to_false(self):
        """Test that generate_group_identify_events defaults to False when not specified"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": "2023-01-01T00:00:00Z",
                "end_date": "2023-01-02T00:00:00Z",
                "access_key": "test-key",
                "secret_key": "test-secret",
                "import_events": True,
                "generate_identify_events": True,
                # generate_group_identify_events not specified
            },
        )

        assert response.status_code == 201

        # Get the created batch import and check its config
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        assert "generate_group_identify_events" in batch_import.import_config
        assert not batch_import.import_config["generate_group_identify_events"]

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

        assert response.status_code == 201

    def test_can_create_import_when_other_team_has_running_import(self):
        """Test that creating a new batch import succeeds when another team has a running import"""
        from posthog.models import Organization, Team

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

        assert response.status_code == 201

    def test_date_range_validation_exceeds_one_year(self):
        """Test that creating a date range import with more than 1 year fails"""

        start_date = datetime(2023, 1, 1, 0, 0, 0)
        end_date = start_date + timedelta(days=366)

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "mixpanel",
                "content_type": "mixpanel",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        assert response.status_code == 400
        assert "Date range cannot exceed 1 year" in str(response.json())

    def test_date_range_validation_within_one_year_succeeds(self):
        """Test that creating a date range import within 1 year succeeds"""

        start_date = datetime(2023, 1, 1, 0, 0, 0)
        end_date = start_date + timedelta(days=300)

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        assert response.status_code == 201

    def test_date_range_validation_end_before_start_fails(self):
        """Test that end date before start date fails validation"""

        start_date = datetime(2023, 6, 1, 0, 0, 0)
        end_date = datetime(2023, 1, 1, 0, 0, 0)

        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "amplitude",
                "content_type": "amplitude",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        assert response.status_code == 400
        assert "End date must be after start date" in str(response.json())

    def test_s3_prefix_can_be_empty_string(self):
        """Test that s3_prefix field accepts empty strings"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "",  # Empty string should be allowed
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        assert response.status_code == 201

        # Verify the batch import was created with empty prefix
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        assert batch_import.import_config["source"]["prefix"] == ""

    def test_s3_prefix_can_be_omitted(self):
        """Test that s3_prefix field can be omitted from the request"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/managed_migrations",
            {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                # s3_prefix omitted entirely
                "access_key": "test-key",
                "secret_key": "test-secret",
            },
        )

        assert response.status_code == 201

        # Verify the batch import was created
        batch_import = BatchImport.objects.get(id=response.json()["id"])
        assert batch_import is not None

    @parameterized.expand(
        [
            ("running_unclaimed", BatchImport.Status.RUNNING, None, "waiting_to_start"),
            ("running_claimed", BatchImport.Status.RUNNING, "worker-uuid-123", "running"),
            ("paused", BatchImport.Status.PAUSED, None, "paused"),
            ("completed", BatchImport.Status.COMPLETED, None, "completed"),
            ("failed", BatchImport.Status.FAILED, None, "failed"),
        ]
    )
    def test_display_status(self, _name, status, lease_id, expected_display_status):
        batch_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test"},
            status=status,
            lease_id=lease_id,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/managed_migrations")

        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(batch_import.id)
        assert results[0]["display_status"] == expected_display_status

    def test_resume_clears_lease_and_backoff(self):
        batch_import = BatchImport.objects.create(
            team=self.team,
            created_by_id=self.user.id,
            import_config={"source": {"type": "s3"}},
            secrets={"access_key": "test"},
            status=BatchImport.Status.PAUSED,
            lease_id="old-lease-uuid",
            leased_until=datetime.now(tz=UTC) + timedelta(hours=1),
            backoff_attempt=5,
            backoff_until=datetime.now(tz=UTC) + timedelta(hours=1),
        )

        response = self.client.post(f"/api/projects/{self.team.id}/managed_migrations/{batch_import.id}/resume")

        assert response.status_code == 200
        batch_import.refresh_from_db()
        assert batch_import.status == BatchImport.Status.RUNNING
        assert batch_import.lease_id is None
        assert batch_import.leased_until is None
        assert batch_import.backoff_attempt == 0
        assert batch_import.backoff_until is None
        assert batch_import.status_message == "Resumed by user"
