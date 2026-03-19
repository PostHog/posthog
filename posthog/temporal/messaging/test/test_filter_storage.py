from unittest.mock import patch

import fakeredis

from posthog.temporal.messaging.filter_storage import get_filters, store_filters
from posthog.temporal.messaging.types import PersonPropertyFilter


class TestFilterStorage:
    """Tests for the filter storage module."""

    def setup_method(self):
        """Set up test fixtures."""
        self.test_filters = [
            PersonPropertyFilter(
                condition_hash="age_filter_25",
                bytecode=["mock_bytecode_age_25"],
                cohort_ids=[100],
            ),
            PersonPropertyFilter(
                condition_hash="country_filter_us",
                bytecode=["mock_bytecode_country_us"],
                cohort_ids=[100, 200],
            ),
            PersonPropertyFilter(
                condition_hash="age_filter_35",
                bytecode=["mock_bytecode_age_35"],
                cohort_ids=[200],
            ),
        ]
        self.team_id = 123

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_store_and_get_filters_round_trip(self, mock_get_client):
        """Test storing and retrieving filters works correctly."""
        # Use fakeredis for testing
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        # Store filters
        storage_key = store_filters(self.test_filters, self.team_id)

        # Verify key format
        assert storage_key.startswith("backfill_person_properties_filters:team_123_")
        assert len(storage_key) > 50  # Should contain full hash

        # Retrieve filters
        retrieved_filters = get_filters(storage_key)

        # Verify round-trip correctness
        assert retrieved_filters is not None
        assert len(retrieved_filters) == 3

        for i, retrieved_filter in enumerate(retrieved_filters):
            original = self.test_filters[i]
            assert retrieved_filter.condition_hash == original.condition_hash
            assert retrieved_filter.bytecode == original.bytecode
            assert retrieved_filter.cohort_ids == original.cohort_ids

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_get_filters_missing_key_returns_none(self, mock_get_client):
        """Test that getting a non-existent key returns None."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        # Try to get filters with a non-existent key
        result = get_filters("backfill_person_properties_filters:team_123_nonexistent")

        assert result is None

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_ttl_behavior(self, mock_get_client):
        """Test TTL expiry behavior using fakeredis."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        # Store filters with short TTL
        storage_key = store_filters(self.test_filters, self.team_id, ttl=1)

        # Verify filters can be retrieved immediately
        retrieved_filters = get_filters(storage_key)
        assert retrieved_filters is not None
        assert len(retrieved_filters) == 3

        # Simulate TTL expiry by deleting the key
        fake_redis.delete(storage_key)

        # Verify filters are no longer retrievable
        expired_filters = get_filters(storage_key)
        assert expired_filters is None

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_different_teams_different_keys(self, mock_get_client):
        """Test that different teams get different storage keys for same filters."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        # Store same filters for different teams
        key1 = store_filters(self.test_filters, team_id=123)
        key2 = store_filters(self.test_filters, team_id=456)

        # Keys should be different due to team_id in key generation
        assert key1 != key2
        assert "team_123" in key1
        assert "team_456" in key2

        # Both should be retrievable
        filters1 = get_filters(key1)
        filters2 = get_filters(key2)

        assert filters1 is not None
        assert filters2 is not None
        assert len(filters1) == len(filters2) == 3

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_identical_filters_same_key(self, mock_get_client):
        """Test that identical filters for the same team produce the same key."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        # Store same filters twice
        key1 = store_filters(self.test_filters, self.team_id)
        key2 = store_filters(self.test_filters, self.team_id)

        # Should get the same key (deterministic hashing)
        assert key1 == key2

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_empty_filters_list(self, mock_get_client):
        """Test storing and retrieving empty filters list."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        # Store empty filters
        storage_key = store_filters([], self.team_id)

        # Retrieve and verify
        retrieved_filters = get_filters(storage_key)
        assert retrieved_filters is not None
        assert len(retrieved_filters) == 0

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_custom_ttl(self, mock_get_client):
        """Test storing with custom TTL."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        custom_ttl = 60  # 1 minute
        storage_key = store_filters(self.test_filters, self.team_id, ttl=custom_ttl)

        # Verify the key exists
        retrieved_filters = get_filters(storage_key)
        assert retrieved_filters is not None

        # Check TTL was set (fakeredis should preserve this)
        ttl_remaining = fake_redis.ttl(storage_key)
        assert ttl_remaining > 0
        assert ttl_remaining <= custom_ttl
