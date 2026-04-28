from unittest.mock import patch

import fakeredis

from posthog.temporal.messaging.filter_storage import (
    get_event_filters,
    get_filters_and_properties,
    store_event_filters,
    store_filters,
)
from posthog.temporal.messaging.types import BehavioralEventFilter, PersonPropertyFilter


class TestFilterStorage:
    """Tests for the filter storage module."""

    def setup_method(self):
        """Set up test fixtures."""
        self.test_filters = [
            PersonPropertyFilter(
                condition_hash="age_filter_25",
                bytecode=["mock_bytecode_age_25"],
                cohort_ids=[100],
                property_key="age",
            ),
            PersonPropertyFilter(
                condition_hash="country_filter_us",
                bytecode=["mock_bytecode_country_us"],
                cohort_ids=[100, 200],
                property_key="country",
            ),
            PersonPropertyFilter(
                condition_hash="age_filter_35",
                bytecode=["mock_bytecode_age_35"],
                cohort_ids=[200],
                property_key="age",
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

        # Retrieve filters and properties
        result = get_filters_and_properties(storage_key)

        # Verify round-trip correctness
        assert result is not None
        retrieved_filters, person_properties, combined_bytecode = result
        assert len(retrieved_filters) == 3

        for i, retrieved_filter in enumerate(retrieved_filters):
            original = self.test_filters[i]
            assert retrieved_filter.condition_hash == original.condition_hash
            assert retrieved_filter.bytecode == original.bytecode
            assert retrieved_filter.cohort_ids == original.cohort_ids
            assert retrieved_filter.property_key == original.property_key

        # Also verify person properties are extracted correctly
        assert person_properties == ["age", "country"]  # Sorted alphabetically

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_get_filters_and_properties_missing_key_returns_none(self, mock_get_client):
        """Test that getting a non-existent key returns None."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        # Try to get filters with a non-existent key
        result = get_filters_and_properties("backfill_person_properties_filters:team_123_nonexistent")

        assert result is None

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_ttl_behavior(self, mock_get_client):
        """Test TTL expiry behavior using fakeredis."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        # Store filters with short TTL
        storage_key = store_filters(self.test_filters, self.team_id, ttl=1)

        # Verify filters can be retrieved immediately
        result = get_filters_and_properties(storage_key)
        assert result is not None
        retrieved_filters, person_properties, combined_bytecode = result
        assert len(retrieved_filters) == 3

        # Simulate TTL expiry by deleting the key
        fake_redis.delete(storage_key)

        # Verify filters are no longer retrievable
        expired_result = get_filters_and_properties(storage_key)
        assert expired_result is None

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
        result1 = get_filters_and_properties(key1)
        result2 = get_filters_and_properties(key2)

        assert result1 is not None
        assert result2 is not None
        filters1, _, _ = result1
        filters2, _, _ = result2
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
        result = get_filters_and_properties(storage_key)
        assert result is not None
        retrieved_filters, person_properties, combined_bytecode = result
        assert len(retrieved_filters) == 0
        assert person_properties == []  # Empty filters should result in empty properties

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_custom_ttl(self, mock_get_client):
        """Test storing with custom TTL."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        custom_ttl = 60  # 1 minute
        storage_key = store_filters(self.test_filters, self.team_id, ttl=custom_ttl)

        # Verify the key exists
        result = get_filters_and_properties(storage_key)
        assert result is not None

        # Check TTL was set (fakeredis should preserve this)
        ttl_remaining = fake_redis.ttl(storage_key)
        assert ttl_remaining > 0
        assert ttl_remaining <= custom_ttl

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_filters_with_none_property_keys(self, mock_get_client):
        """Test handling filters with None property_key values."""
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        # Create filters with some None property_key values
        test_filters = [
            PersonPropertyFilter(
                condition_hash="some_filter",
                bytecode=["mock_bytecode"],
                cohort_ids=[100],
                property_key=None,  # None property key
            ),
            PersonPropertyFilter(
                condition_hash="age_filter",
                bytecode=["mock_bytecode_age"],
                cohort_ids=[100],
                property_key="age",
            ),
        ]

        storage_key = store_filters(test_filters, self.team_id)

        # Get both filters and properties
        result = get_filters_and_properties(storage_key)
        assert result is not None

        retrieved_filters, person_properties, combined_bytecode = result

        # Verify person properties only includes non-None keys
        assert person_properties == ["age"]

        # Verify filters are retrieved correctly
        assert len(retrieved_filters) == 2
        assert retrieved_filters[0].property_key is None
        assert retrieved_filters[1].property_key == "age"


class TestEventFilterStorage:
    def setup_method(self):
        self.test_filters = [
            BehavioralEventFilter(
                condition_hash="pageview_hash",
                bytecode=["_H", 1, 32, "$pageview"],
                cohort_ids=[100],
                event_name="$pageview",
                time_value=30,
                time_interval="day",
            ),
            BehavioralEventFilter(
                condition_hash="purchase_hash",
                bytecode=["_H", 1, 32, "purchase"],
                cohort_ids=[100, 200],
                event_name="purchase",
                time_value=7,
                time_interval="day",
            ),
            BehavioralEventFilter(
                condition_hash="pageview_pricing_hash",
                bytecode=["_H", 1, 32, "$pageview", 33, "/pricing"],
                cohort_ids=[200],
                event_name="$pageview",
                time_value=14,
                time_interval="day",
                event_filters=[{"type": "event", "key": "url", "value": "/pricing", "operator": "exact"}],
            ),
        ]
        self.team_id = 123

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_store_and_get_round_trip(self, mock_get_client):
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        storage_key = store_event_filters(self.test_filters, self.team_id)

        assert storage_key.startswith("backfill_event_filters:team_123_")
        assert len(storage_key) > 50

        result = get_event_filters(storage_key)
        assert result is not None

        retrieved_filters, event_names, combined_bytecodes = result
        assert len(retrieved_filters) == 3

        for i, retrieved in enumerate(retrieved_filters):
            original = self.test_filters[i]
            assert retrieved.condition_hash == original.condition_hash
            assert retrieved.bytecode == original.bytecode
            assert retrieved.cohort_ids == original.cohort_ids
            assert retrieved.event_name == original.event_name
            assert retrieved.time_value == original.time_value
            assert retrieved.time_interval == original.time_interval
            assert retrieved.event_filters == original.event_filters

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_event_names_extracted_and_sorted(self, mock_get_client):
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        storage_key = store_event_filters(self.test_filters, self.team_id)
        result = get_event_filters(storage_key)
        assert result is not None

        _, event_names, _ = result
        assert event_names == ["$pageview", "purchase"]

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_combined_bytecodes_grouped_by_event_name(self, mock_get_client):
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        storage_key = store_event_filters(self.test_filters, self.team_id)
        result = get_event_filters(storage_key)
        assert result is not None

        _, _, combined_bytecodes = result

        # Two groups: $pageview (2 filters) and purchase (1 filter)
        assert "$pageview" in combined_bytecodes
        assert "purchase" in combined_bytecodes
        assert len(combined_bytecodes) == 2

        # Each combined bytecode should start with the bytecode identifier
        for bytecode in combined_bytecodes.values():
            assert bytecode[0] == "_H"

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_missing_key_returns_none(self, mock_get_client):
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        result = get_event_filters("backfill_event_filters:team_123_nonexistent")
        assert result is None

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_different_teams_different_keys(self, mock_get_client):
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        key1 = store_event_filters(self.test_filters, team_id=123)
        key2 = store_event_filters(self.test_filters, team_id=456)

        assert key1 != key2
        assert "team_123" in key1
        assert "team_456" in key2

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_identical_filters_same_key(self, mock_get_client):
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        key1 = store_event_filters(self.test_filters, self.team_id)
        key2 = store_event_filters(self.test_filters, self.team_id)

        assert key1 == key2

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_empty_filters(self, mock_get_client):
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        storage_key = store_event_filters([], self.team_id)
        result = get_event_filters(storage_key)

        assert result is not None
        filters, event_names, combined_bytecodes = result
        assert len(filters) == 0
        assert event_names == []
        assert combined_bytecodes == {}

    @patch("posthog.temporal.messaging.filter_storage.get_client")
    def test_single_event_name_group(self, mock_get_client):
        fake_redis = fakeredis.FakeRedis()
        mock_get_client.return_value = fake_redis

        single_event_filters = [
            BehavioralEventFilter(
                condition_hash="hash1",
                bytecode=["_H", 1, 32, "$pageview"],
                cohort_ids=[100],
                event_name="$pageview",
                time_value=30,
                time_interval="day",
            ),
            BehavioralEventFilter(
                condition_hash="hash2",
                bytecode=["_H", 1, 32, "$pageview", 33, "extra"],
                cohort_ids=[200],
                event_name="$pageview",
                time_value=7,
                time_interval="day",
            ),
        ]

        storage_key = store_event_filters(single_event_filters, self.team_id)
        result = get_event_filters(storage_key)
        assert result is not None

        _, event_names, combined_bytecodes = result
        assert event_names == ["$pageview"]
        assert len(combined_bytecodes) == 1
        assert "$pageview" in combined_bytecodes
