from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

from posthog.temporal.weekly_digest.activities import (
    count_organizations,
    count_teams,
    generate_dashboard_lookup,
    generate_event_definition_lookup,
    generate_experiment_completed_lookup,
    generate_experiment_launched_lookup,
    generate_external_data_source_lookup,
    generate_feature_flag_lookup,
    generate_filter_lookup,
    generate_organization_digest_batch,
    generate_recording_lookup,
    generate_survey_lookup,
    generate_user_notification_lookup,
    send_weekly_digest_batch,
)
from posthog.temporal.weekly_digest.types import (
    CommonInput,
    Digest,
    GenerateDigestDataBatchInput,
    GenerateOrganizationDigestInput,
    SendWeeklyDigestBatchInput,
)


class MockRedis:
    """Mock Redis client for testing."""

    def __init__(self):
        self.data = {}
        self.sets = {}
        self.ttls = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value
        self.ttls[key] = ttl

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.data.get(key) for key in keys]

    async def sadd(self, key: str, *values) -> None:
        if key not in self.sets:
            self.sets[key] = set()
        self.sets[key].update(values)

    async def smembers(self, key: str) -> set:
        return self.sets.get(key, set())

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockAsyncQuerySet:
    """Mock Django async queryset for testing."""

    def __init__(self, items):
        self.items = items

    def __getitem__(self, key):
        """Support slicing operations."""
        if isinstance(key, slice):
            return MockAsyncQuerySet(self.items[key])
        return self.items[key]

    def __aiter__(self):
        """Support async iteration."""
        return self

    async def __anext__(self):
        """Async iterator implementation."""
        if not hasattr(self, "_iter"):
            self._iter = iter(self.items)
        try:
            return next(self._iter)
        except StopIteration:
            delattr(self, "_iter")
            raise StopAsyncIteration


@pytest.fixture
def mock_redis():
    """Fixture providing a mock Redis instance."""
    return MockRedis()


@pytest.fixture
def common_input():
    """Fixture providing common input parameters."""
    return CommonInput(
        redis_ttl=3600 * 24 * 3,
        redis_host="localhost",
        redis_port=6379,
        batch_size=10,
        django_redis_url="redis://localhost:6379",
    )


@pytest.fixture
def digest():
    """Fixture providing a test digest."""
    period_end = datetime.now(UTC)
    period_start = period_end - timedelta(days=7)
    return Digest(key="test-digest", period_start=period_start, period_end=period_end)


@pytest_asyncio.fixture(autouse=True)
async def mock_heartbeater():
    """Auto-fixture to mock Heartbeater for all tests."""
    with patch("posthog.temporal.weekly_digest.activities.Heartbeater"):
        yield


@pytest.mark.asyncio
async def test_count_teams():
    """Test counting teams for digest."""
    mock_queryset = AsyncMock()
    mock_queryset.acount = AsyncMock(return_value=42)

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_queryset):
        result = await count_teams()

    assert result == 42
    mock_queryset.acount.assert_called_once()


@pytest.mark.asyncio
async def test_count_organizations():
    """Test counting organizations for digest."""
    mock_queryset = AsyncMock()
    mock_queryset.acount = AsyncMock(return_value=15)

    with patch("posthog.temporal.weekly_digest.activities.query_orgs_for_digest", return_value=mock_queryset):
        result = await count_organizations()

    assert result == 15
    mock_queryset.acount.assert_called_once()


@pytest.mark.asyncio
async def test_generate_dashboard_lookup(mock_redis, common_input, digest):
    """Test generating dashboard lookup with mock Redis."""
    batch = (0, 2)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    # Mock teams
    mock_team_1 = MagicMock()
    mock_team_1.id = 1
    mock_team_2 = MagicMock()
    mock_team_2.id = 2

    # Mock dashboards
    mock_dashboards = [
        {"team_id": 1, "name": "Dashboard 1", "id": 101},
        {"team_id": 1, "name": "Dashboard 2", "id": 102},
    ]

    mock_team_queryset = MockAsyncQuerySet([mock_team_1, mock_team_2])
    mock_dashboard_queryset = MagicMock()

    async def mock_queryset_to_list(qs):
        if qs == mock_dashboard_queryset:
            return mock_dashboards
        return []

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch(
            "posthog.temporal.weekly_digest.activities.query_new_dashboards", return_value=mock_dashboard_queryset
        ):
            with patch("posthog.temporal.weekly_digest.activities.queryset_to_list", side_effect=mock_queryset_to_list):
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                    await generate_dashboard_lookup(input_data)

    # Verify data was stored in Redis
    assert f"{digest.key}-dashboards-1" in mock_redis.data
    assert mock_redis.ttls[f"{digest.key}-dashboards-1"] == common_input.redis_ttl


@pytest.mark.asyncio
async def test_generate_event_definition_lookup(mock_redis, common_input, digest):
    """Test generating event definition lookup with mock Redis."""
    batch = (0, 1)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    mock_team = MagicMock()
    mock_team.id = 1

    mock_events = [
        {"team_id": 1, "name": "pageview", "id": str(uuid4())},
        {"team_id": 1, "name": "click", "id": str(uuid4())},
    ]

    mock_team_queryset = MockAsyncQuerySet([mock_team])

    mock_event_queryset = MagicMock()

    async def mock_queryset_to_list(qs):
        if qs == mock_event_queryset:
            return mock_events
        return []

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch(
            "posthog.temporal.weekly_digest.activities.query_new_event_definitions", return_value=mock_event_queryset
        ):
            with patch("posthog.temporal.weekly_digest.activities.queryset_to_list", side_effect=mock_queryset_to_list):
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                    await generate_event_definition_lookup(input_data)

    assert f"{digest.key}-event-definitions-1" in mock_redis.data


@pytest.mark.asyncio
async def test_generate_experiment_launched_lookup(mock_redis, common_input, digest):
    """Test generating experiment launched lookup with mock Redis."""
    batch = (0, 1)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    mock_team = MagicMock()
    mock_team.id = 1

    mock_experiments = [
        {"team_id": 1, "name": "Experiment A", "id": 1, "start_date": datetime.now(UTC)},
        {"team_id": 1, "name": "Experiment B", "id": 2, "start_date": datetime.now(UTC)},
    ]

    mock_team_queryset = MockAsyncQuerySet([mock_team])

    mock_experiment_queryset = MagicMock()

    async def mock_queryset_to_list(qs):
        if qs == mock_experiment_queryset:
            return mock_experiments
        return []

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch(
            "posthog.temporal.weekly_digest.activities.query_experiments_launched",
            return_value=mock_experiment_queryset,
        ):
            with patch("posthog.temporal.weekly_digest.activities.queryset_to_list", side_effect=mock_queryset_to_list):
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                    await generate_experiment_launched_lookup(input_data)

    assert f"{digest.key}-experiments-launched-1" in mock_redis.data


@pytest.mark.asyncio
async def test_generate_experiment_completed_lookup(mock_redis, common_input, digest):
    """Test generating experiment completed lookup with mock Redis."""
    batch = (0, 1)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    mock_team = MagicMock()
    mock_team.id = 1

    mock_experiments = [
        {
            "team_id": 1,
            "name": "Completed Experiment",
            "id": 1,
            "start_date": datetime.now(UTC) - timedelta(days=14),
            "end_date": datetime.now(UTC) - timedelta(days=1),
        }
    ]

    mock_team_queryset = MockAsyncQuerySet([mock_team])

    mock_experiment_queryset = MagicMock()

    async def mock_queryset_to_list(qs):
        if qs == mock_experiment_queryset:
            return mock_experiments
        return []

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch(
            "posthog.temporal.weekly_digest.activities.query_experiments_completed",
            return_value=mock_experiment_queryset,
        ):
            with patch("posthog.temporal.weekly_digest.activities.queryset_to_list", side_effect=mock_queryset_to_list):
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                    await generate_experiment_completed_lookup(input_data)

    assert f"{digest.key}-experiments-completed-1" in mock_redis.data


@pytest.mark.asyncio
async def test_generate_external_data_source_lookup(mock_redis, common_input, digest):
    """Test generating external data source lookup with mock Redis."""
    batch = (0, 1)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    mock_team = MagicMock()
    mock_team.id = 1

    mock_sources = [{"team_id": 1, "source_type": "stripe", "id": str(uuid4())}]

    mock_team_queryset = MockAsyncQuerySet([mock_team])

    mock_source_queryset = MagicMock()

    async def mock_queryset_to_list(qs):
        if qs == mock_source_queryset:
            return mock_sources
        return []

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch(
            "posthog.temporal.weekly_digest.activities.query_new_external_data_sources",
            return_value=mock_source_queryset,
        ):
            with patch("posthog.temporal.weekly_digest.activities.queryset_to_list", side_effect=mock_queryset_to_list):
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                    await generate_external_data_source_lookup(input_data)

    assert f"{digest.key}-external-data-sources-1" in mock_redis.data


@pytest.mark.asyncio
async def test_generate_feature_flag_lookup(mock_redis, common_input, digest):
    """Test generating feature flag lookup with mock Redis."""
    batch = (0, 1)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    mock_team = MagicMock()
    mock_team.id = 1

    mock_flags = [
        {"team_id": 1, "name": "New Feature", "id": 1, "key": "new-feature"},
        {"team_id": 1, "name": "Beta Feature", "id": 2, "key": "beta-feature"},
    ]

    mock_team_queryset = MockAsyncQuerySet([mock_team])

    mock_flag_queryset = MagicMock()

    async def mock_queryset_to_list(qs):
        if qs == mock_flag_queryset:
            return mock_flags
        return []

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch(
            "posthog.temporal.weekly_digest.activities.query_new_feature_flags", return_value=mock_flag_queryset
        ):
            with patch("posthog.temporal.weekly_digest.activities.queryset_to_list", side_effect=mock_queryset_to_list):
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                    await generate_feature_flag_lookup(input_data)

    assert f"{digest.key}-feature-flags-1" in mock_redis.data


@pytest.mark.asyncio
async def test_generate_survey_lookup(mock_redis, common_input, digest):
    """Test generating survey lookup with mock Redis."""
    batch = (0, 1)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    mock_team = MagicMock()
    mock_team.id = 1

    mock_surveys = [
        {
            "team_id": 1,
            "name": "Customer Satisfaction",
            "id": str(uuid4()),
            "description": "How satisfied are you?",
            "start_date": datetime.now(UTC),
        }
    ]

    mock_team_queryset = MockAsyncQuerySet([mock_team])

    mock_survey_queryset = MagicMock()

    async def mock_queryset_to_list(qs):
        if qs == mock_survey_queryset:
            return mock_surveys
        return []

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch(
            "posthog.temporal.weekly_digest.activities.query_surveys_launched", return_value=mock_survey_queryset
        ):
            with patch("posthog.temporal.weekly_digest.activities.queryset_to_list", side_effect=mock_queryset_to_list):
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                    await generate_survey_lookup(input_data)

    assert f"{digest.key}-surveys-launched-1" in mock_redis.data


@pytest.mark.asyncio
async def test_generate_filter_lookup(mock_redis, common_input, digest):
    """Test generating filter lookup with mock Redis and playlist counts."""
    batch = (0, 1)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    mock_team = MagicMock()
    mock_team.id = 1

    mock_filters = [
        {"name": "High Value Users", "short_id": "abc123", "view_count": 5},
        {"name": "Error Tracking", "short_id": "def456", "view_count": 3},
    ]

    # Mock playlist count data
    mock_django_redis = MockRedis()
    await mock_django_redis.setex(
        "posthog:1:playlist:abc123:count",
        3600,
        '{"session_ids": ["session1", "session2"], "has_more": false, "previous_ids": null, "refreshed_at": "2024-01-01T00:00:00Z", "error_count": 0, "errored_at": null}',
    )
    await mock_django_redis.setex(
        "posthog:1:playlist:def456:count",
        3600,
        '{"session_ids": ["session3"], "has_more": true, "previous_ids": null, "refreshed_at": "2024-01-01T00:00:00Z", "error_count": 0, "errored_at": null}',
    )

    mock_team_queryset = MockAsyncQuerySet([mock_team])

    mock_filter_queryset = MagicMock()

    async def mock_queryset_to_list(qs):
        if qs == mock_filter_queryset:
            return mock_filters
        return []

    def mock_redis_from_url(url):
        if "django" in url.lower() or url == common_input.django_redis_url:
            return mock_django_redis
        return mock_redis

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch("posthog.temporal.weekly_digest.activities.query_saved_filters", return_value=mock_filter_queryset):
            with patch("posthog.temporal.weekly_digest.activities.queryset_to_list", side_effect=mock_queryset_to_list):
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", side_effect=mock_redis_from_url):
                    await generate_filter_lookup(input_data)

    assert f"{digest.key}-saved-filters-1" in mock_redis.data


@pytest.mark.asyncio
async def test_generate_recording_lookup(mock_redis, common_input, digest):
    """Test generating recording lookup with mock Redis and ClickHouse."""
    batch = (0, 1)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    mock_team = MagicMock()
    mock_team.id = 1

    mock_ch_response = AsyncMock()
    mock_ch_response.content.read = AsyncMock(
        return_value=b'{"meta": [], "data": [{"session_id": "session123", "recording_ttl": 10}], "statistics": {}, "rows": 1}'
    )
    mock_ch_response.__aenter__ = AsyncMock(return_value=mock_ch_response)
    mock_ch_response.__aexit__ = AsyncMock(return_value=None)

    mock_team_queryset = MockAsyncQuerySet([mock_team])

    mock_ch_client = AsyncMock()
    mock_ch_client.aget_query = MagicMock(return_value=mock_ch_response)
    mock_ch_client.__aenter__ = AsyncMock(return_value=mock_ch_client)
    mock_ch_client.__aexit__ = AsyncMock(return_value=None)

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch("posthog.temporal.weekly_digest.activities.get_ch_client", return_value=mock_ch_client):
            with patch("posthog.temporal.weekly_digest.activities.database_sync_to_async") as mock_sync:
                mock_sync.return_value = AsyncMock(return_value=30)
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                    await generate_recording_lookup(input_data)

    assert f"{digest.key}-expiring-recordings-1" in mock_redis.data


@pytest.mark.asyncio
async def test_generate_user_notification_lookup(mock_redis, common_input, digest):
    """Test generating user notification lookup with mock Redis."""
    batch = (0, 1)
    input_data = GenerateDigestDataBatchInput(batch=batch, digest=digest, common=common_input)

    mock_team = MagicMock()
    mock_team.id = 1

    mock_user_1 = MagicMock()
    mock_user_1.id = 100

    mock_user_2 = MagicMock()
    mock_user_2.id = 101

    # Create a sync function that database_sync_to_async will wrap
    def sync_all_users_with_access():
        return [mock_user_1, mock_user_2]

    mock_team.all_users_with_access = sync_all_users_with_access

    mock_team_queryset = MockAsyncQuerySet([mock_team])

    # Create an async generator function
    async def async_user_generator():
        for user in [mock_user_1, mock_user_2]:
            yield user

    # Create a coroutine that returns the async generator
    async def async_wrapper():
        return async_user_generator()

    with patch("posthog.temporal.weekly_digest.activities.query_teams_for_digest", return_value=mock_team_queryset):
        with patch("posthog.temporal.weekly_digest.activities.should_send_notification", return_value=True):
            with patch("posthog.temporal.weekly_digest.activities.database_sync_to_async") as mock_sync:
                # database_sync_to_async(fn)() should return an awaitable that yields an async generator
                mock_sync.return_value = async_wrapper
                with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                    await generate_user_notification_lookup(input_data)

    # Verify user notification sets were created
    assert f"{digest.key}-user-notify-100" in mock_redis.sets
    assert f"{digest.key}-user-notify-101" in mock_redis.sets
    assert 1 in mock_redis.sets[f"{digest.key}-user-notify-100"]
    assert 1 in mock_redis.sets[f"{digest.key}-user-notify-101"]


@pytest.mark.asyncio
async def test_generate_organization_digest_batch(mock_redis, common_input, digest):
    """Test generating organization digest batch with mock Redis."""
    batch = (0, 1)
    input_data = GenerateOrganizationDigestInput(batch=batch, digest=digest, common=common_input)

    mock_org = MagicMock()
    mock_org.id = UUID("12345678-1234-1234-1234-123456789abc")
    mock_org.name = "Test Organization"
    mock_org.created_at = datetime.now(UTC)

    mock_team = MagicMock()
    mock_team.id = 1
    mock_team.name = "Test Team"

    # Pre-populate Redis with team digest data
    await mock_redis.setex(f"{digest.key}-dashboards-1", 3600, "[]")
    await mock_redis.setex(f"{digest.key}-event-definitions-1", 3600, "[]")
    await mock_redis.setex(f"{digest.key}-experiments-launched-1", 3600, "[]")
    await mock_redis.setex(f"{digest.key}-experiments-completed-1", 3600, "[]")
    await mock_redis.setex(f"{digest.key}-external-data-sources-1", 3600, "[]")
    await mock_redis.setex(f"{digest.key}-feature-flags-1", 3600, "[]")
    await mock_redis.setex(f"{digest.key}-saved-filters-1", 3600, "[]")
    await mock_redis.setex(f"{digest.key}-expiring-recordings-1", 3600, "[]")
    await mock_redis.setex(f"{digest.key}-surveys-launched-1", 3600, "[]")

    mock_org_queryset = MockAsyncQuerySet([mock_org])
    mock_team_queryset = MockAsyncQuerySet([mock_team])

    with patch("posthog.temporal.weekly_digest.activities.query_orgs_for_digest", return_value=mock_org_queryset):
        with patch("posthog.temporal.weekly_digest.activities.query_org_teams", return_value=mock_team_queryset):
            with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                await generate_organization_digest_batch(input_data)

    # Verify organization digest was created
    assert f"{digest.key}-{mock_org.id}" in mock_redis.data


@pytest.mark.asyncio
async def test_send_weekly_digest_batch(mock_redis, common_input, digest):
    """Test sending weekly digest batch with mock Redis and PostHog client."""
    batch = (0, 1)
    input_data = SendWeeklyDigestBatchInput(batch=batch, dry_run=False, digest=digest, common=common_input)

    mock_org = MagicMock()
    mock_org.id = UUID("12345678-1234-1234-1234-123456789abc")
    mock_org.name = "Test Organization"

    mock_member = MagicMock()
    mock_user = MagicMock()
    mock_user.id = 100
    mock_user.distinct_id = "user-100"
    mock_user.email = "test@example.com"
    mock_member.user = mock_user

    # Pre-populate Redis with organization digest
    org_digest_json = """{
        "id": "12345678-1234-1234-1234-123456789abc",
        "name": "Test Organization",
        "created_at": "2024-01-01T00:00:00Z",
        "team_digests": [
            {
                "id": 1,
                "name": "Test Team",
                "dashboards": [{"name": "Test Dashboard", "id": 1}],
                "event_definitions": [],
                "experiments_launched": [],
                "experiments_completed": [],
                "external_data_sources": [],
                "feature_flags": [],
                "filters": [],
                "recordings": [],
                "surveys_launched": []
            }
        ]
    }"""
    await mock_redis.setex(f"{digest.key}-{mock_org.id}", 3600, org_digest_json)

    # Add user notification
    await mock_redis.sadd(f"{digest.key}-user-notify-100", "1")

    mock_org_queryset = MockAsyncQuerySet([mock_org])
    mock_member_queryset = MockAsyncQuerySet([mock_member])

    mock_ph_client = MagicMock()
    mock_ph_client.capture = MagicMock()
    mock_ph_client.flush = MagicMock()
    mock_ph_client.shutdown = MagicMock()

    mock_messaging_record = MagicMock()
    mock_messaging_record.sent_at = None
    mock_messaging_record.asave = AsyncMock()

    mock_messaging_objects = MagicMock()
    mock_messaging_objects.aget_or_create = AsyncMock(return_value=(mock_messaging_record, True))

    with patch("posthog.temporal.weekly_digest.activities.query_orgs_for_digest", return_value=mock_org_queryset):
        with patch("posthog.temporal.weekly_digest.activities.query_org_members", return_value=mock_member_queryset):
            with patch("posthog.temporal.weekly_digest.activities.get_regional_ph_client", return_value=mock_ph_client):
                with patch("posthog.temporal.weekly_digest.activities.MessagingRecord.objects", mock_messaging_objects):
                    with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                        await send_weekly_digest_batch(input_data)

    # Verify PostHog client was called
    mock_ph_client.capture.assert_called_once()
    mock_ph_client.flush.assert_called_once()
    mock_ph_client.shutdown.assert_called_once()

    # Verify messaging record was updated
    mock_messaging_record.asave.assert_called_once()


@pytest.mark.asyncio
async def test_send_weekly_digest_batch_dry_run(mock_redis, common_input, digest):
    """Test sending weekly digest batch in dry run mode."""
    batch = (0, 1)
    input_data = SendWeeklyDigestBatchInput(batch=batch, dry_run=True, digest=digest, common=common_input)

    mock_org = MagicMock()
    mock_org.id = UUID("12345678-1234-1234-1234-123456789abc")
    mock_org.name = "Test Organization"

    mock_member = MagicMock()
    mock_user = MagicMock()
    mock_user.id = 100
    mock_user.distinct_id = "user-100"
    mock_user.email = "test@example.com"
    mock_member.user = mock_user

    # Pre-populate Redis with organization digest
    org_digest_json = """{
        "id": "12345678-1234-1234-1234-123456789abc",
        "name": "Test Organization",
        "created_at": "2024-01-01T00:00:00Z",
        "team_digests": [
            {
                "id": 1,
                "name": "Test Team",
                "dashboards": [{"name": "Test Dashboard", "id": 1}],
                "event_definitions": [],
                "experiments_launched": [],
                "experiments_completed": [],
                "external_data_sources": [],
                "feature_flags": [],
                "filters": [],
                "recordings": [],
                "surveys_launched": []
            }
        ]
    }"""
    await mock_redis.setex(f"{digest.key}-{mock_org.id}", 3600, org_digest_json)

    # Add user notification
    await mock_redis.sadd(f"{digest.key}-user-notify-100", "1")

    mock_org_queryset = MockAsyncQuerySet([mock_org])
    mock_member_queryset = MockAsyncQuerySet([mock_member])

    mock_ph_client = MagicMock()
    mock_ph_client.capture = MagicMock()
    mock_ph_client.shutdown = MagicMock()

    mock_messaging_record = MagicMock()
    mock_messaging_record.sent_at = None

    mock_messaging_objects = MagicMock()
    mock_messaging_objects.aget_or_create = AsyncMock(return_value=(mock_messaging_record, True))

    with patch("posthog.temporal.weekly_digest.activities.query_orgs_for_digest", return_value=mock_org_queryset):
        with patch("posthog.temporal.weekly_digest.activities.query_org_members", return_value=mock_member_queryset):
            with patch("posthog.temporal.weekly_digest.activities.get_regional_ph_client", return_value=mock_ph_client):
                with patch("posthog.temporal.weekly_digest.activities.MessagingRecord.objects", mock_messaging_objects):
                    with patch("posthog.temporal.weekly_digest.activities.redis.from_url", return_value=mock_redis):
                        await send_weekly_digest_batch(input_data)

    # In dry run mode, PostHog client should not be called
    mock_ph_client.capture.assert_not_called()
    mock_ph_client.shutdown.assert_called_once()
