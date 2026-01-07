import json

from posthog.test.base import BaseTest

from posthog.models.event_ingestion_restriction_config import (
    DYNAMIC_CONFIG_REDIS_KEY_PREFIX,
    EventIngestionRestrictionConfig,
    RestrictionType,
)
from posthog.redis import get_client


class TestEventIngestionRestrictionConfig(BaseTest):
    def setUp(self):
        super().setUp()
        self.redis_client = get_client()
        for key in self.redis_client.keys(f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:*"):
            self.redis_client.delete(key)

    def test_model_creation(self):
        """Test basic model creation and properties"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id1", "id2"],
            pipelines=["analytics"],
        )

        assert config.token == "test_token"
        assert config.restriction_type == RestrictionType.SKIP_PERSON_PROCESSING
        assert config.distinct_ids == ["id1", "id2"]
        assert config.pipelines == ["analytics"]
        assert config.get_redis_key() == f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.SKIP_PERSON_PROCESSING}"

    def test_post_save_signal_with_distinct_ids(self):
        """Test that post_save signal correctly updates Redis when model has distinct_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["id1", "id2"],
            pipelines=["analytics", "session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "distinct_id": "id1", "pipelines": ["analytics", "session_recordings"]},
            {"token": "test_token", "distinct_id": "id2", "pipelines": ["analytics", "session_recordings"]},
        ]
        assert sorted(data, key=lambda x: x["distinct_id"]) == sorted(expected_entries, key=lambda x: x["distinct_id"])

    def test_post_save_signal_without_distinct_ids(self):
        """Test that post_save signal correctly updates Redis when model has no distinct_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "test_token", "pipelines": ["analytics"]}]

    def test_post_save_signal_with_existing_data(self):
        """Test that post_save signal correctly merges with existing Redis data"""
        EventIngestionRestrictionConfig.objects.create(
            token="existing_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["existing_id"],
            pipelines=["session_recordings"],
        )

        second_config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id1", "id2"],
            pipelines=["analytics"],
        )

        redis_key = second_config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 3

        expected_entries = [
            {"token": "existing_token", "distinct_id": "existing_id", "pipelines": ["session_recordings"]},
            {"token": "test_token", "distinct_id": "id1", "pipelines": ["analytics"]},
            {"token": "test_token", "distinct_id": "id2", "pipelines": ["analytics"]},
        ]

        def sort_key(x):
            return (x["token"], x.get("distinct_id", ""))

        assert sorted(data, key=sort_key) == sorted(expected_entries, key=sort_key)

    def test_post_delete_signal_with_distinct_ids(self):
        """Test that post_delete signal correctly updates Redis when deleting a model with distinct_ids"""
        EventIngestionRestrictionConfig.objects.create(
            token="other_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            pipelines=["analytics"],
        )

        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["id1", "id2"],
            pipelines=["session_recordings"],
        )

        config.delete()

        redis_key = f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.DROP_EVENT_FROM_INGESTION}"
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "other_token", "pipelines": ["analytics"]}]

    def test_post_delete_signal_without_distinct_ids(self):
        """Test that post_delete signal correctly updates Redis when deleting a model without distinct_ids"""
        EventIngestionRestrictionConfig.objects.create(
            token="other_token",
            restriction_type=RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
            pipelines=["analytics", "session_recordings"],
        )

        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
            pipelines=["analytics"],
        )

        config.delete()

        redis_key = f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.FORCE_OVERFLOW_FROM_INGESTION}"
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "other_token", "pipelines": ["analytics", "session_recordings"]}]

    def test_post_delete_signal_removes_key_when_empty(self):
        """Test that post_delete signal removes Redis key when no data remains"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        assert self.redis_client.get(redis_key) is not None

        config.delete()

        assert self.redis_client.get(redis_key) is None

    def test_update_config_distinct_ids(self):
        """Test that updating a config's distinct_ids correctly updates Redis cache"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id1", "id2"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        config.distinct_ids = ["id2", "id3"]  # Remove id1, keep id2, add id3
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "distinct_id": "id2", "pipelines": ["analytics"]},
            {"token": "test_token", "distinct_id": "id3", "pipelines": ["analytics"]},
        ]
        assert sorted(data, key=lambda x: x["distinct_id"]) == sorted(expected_entries, key=lambda x: x["distinct_id"])
        assert "id1" not in [entry.get("distinct_id") for entry in data]

    def test_update_config_remove_all_distinct_ids(self):
        """Test that removing all distinct_ids correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id1", "id2"],
            pipelines=["analytics"],
        )

        config.distinct_ids = []
        config.save()

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "test_token", "pipelines": ["analytics"]}]
        assert "id1" not in [entry.get("distinct_id", "") for entry in data]
        assert "id2" not in [entry.get("distinct_id", "") for entry in data]

    def test_update_config_add_distinct_ids(self):
        """Test that adding distinct_ids to a config without them correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token", restriction_type=RestrictionType.SKIP_PERSON_PROCESSING, pipelines=["analytics"]
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "test_token", "pipelines": ["analytics"]}]

        config.distinct_ids = ["id1", "id2"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        expected_entries = [
            {"token": "test_token", "distinct_id": "id1", "pipelines": ["analytics"]},
            {"token": "test_token", "distinct_id": "id2", "pipelines": ["analytics"]},
        ]
        assert sorted(data, key=lambda x: x.get("distinct_id", "")) == sorted(
            expected_entries, key=lambda x: x.get("distinct_id", "")
        )
        # Verify the token-only entry was removed
        assert {"token": "test_token", "pipelines": ["analytics"]} not in data

    def test_pipeline_fields_in_redis(self):
        """Test that pipelines field is correctly stored in Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            pipelines=["session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")

        assert data == [{"token": "test_token", "pipelines": ["session_recordings"]}]

    def test_update_pipeline_fields(self):
        """Test that updating pipelines field correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "test_token", "pipelines": ["analytics"]}]

        config.pipelines = ["session_recordings"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "test_token", "pipelines": ["session_recordings"]}]

    def test_pipeline_fields_with_distinct_ids(self):
        """Test that pipelines field works correctly with distinct_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id1", "id2"],
            pipelines=["session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")

        expected_entries = [
            {"token": "test_token", "distinct_id": "id1", "pipelines": ["session_recordings"]},
            {"token": "test_token", "distinct_id": "id2", "pipelines": ["session_recordings"]},
        ]
        assert sorted(data, key=lambda x: x["distinct_id"]) == sorted(expected_entries, key=lambda x: x["distinct_id"])

    def test_regenerate_redis_removes_deleted_entries(self):
        """Test that deleting a config regenerates Redis and removes only that config's entries"""
        # Create two configs with same restriction type
        config1 = EventIngestionRestrictionConfig.objects.create(
            token="test_token_1",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            pipelines=["analytics"],
        )

        EventIngestionRestrictionConfig.objects.create(
            token="test_token_2",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            pipelines=["session_recordings"],
        )

        redis_key = config1.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        # Delete the first config
        config1.delete()

        # Verify only config2 remains in Redis
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 1
        assert data == [{"token": "test_token_2", "pipelines": ["session_recordings"]}]

    def test_regenerate_redis_with_multiple_configs_different_pipelines(self):
        """Test that regenerating Redis correctly handles multiple configs with different pipelines"""
        # Create configs with same token but in different restriction types (allowed by unique_together)
        config1 = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            pipelines=["analytics"],
        )

        config2 = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
            pipelines=["session_recordings"],
        )

        # Check that each restriction type has its own Redis key with correct data
        redis_key1 = config1.get_redis_key()
        redis_data1 = self.redis_client.get(redis_key1)
        data1 = json.loads(redis_data1 if redis_data1 is not None else b"[]")
        assert data1 == [{"token": "test_token", "pipelines": ["analytics"]}]

        redis_key2 = config2.get_redis_key()
        redis_data2 = self.redis_client.get(redis_key2)
        data2 = json.loads(redis_data2 if redis_data2 is not None else b"[]")
        assert data2 == [{"token": "test_token", "pipelines": ["session_recordings"]}]

        # Delete config1, verify it's removed from its Redis key but config2 remains
        config1.delete()

        redis_data1 = self.redis_client.get(redis_key1)
        assert redis_data1 is None

        redis_data2 = self.redis_client.get(redis_key2)
        assert redis_data2 is not None
        data2 = json.loads(redis_data2 if redis_data2 is not None else b"[]")
        assert data2 == [{"token": "test_token", "pipelines": ["session_recordings"]}]

    def test_regenerate_redis_preserves_other_configs(self):
        """Test that updating one config doesn't affect other configs in the same restriction type"""
        config1 = EventIngestionRestrictionConfig.objects.create(
            token="test_token_1",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id1"],
            pipelines=["analytics"],
        )

        EventIngestionRestrictionConfig.objects.create(
            token="test_token_2",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id2"],
            pipelines=["session_recordings"],
        )

        # Update config1
        config1.pipelines = ["analytics", "session_recordings"]
        config1.save()

        # Verify both configs are in Redis with correct values
        redis_key = config1.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")

        assert len(data) == 2
        assert {"token": "test_token_1", "distinct_id": "id1", "pipelines": ["analytics", "session_recordings"]} in data
        assert {"token": "test_token_2", "distinct_id": "id2", "pipelines": ["session_recordings"]} in data

    def test_post_save_signal_with_session_ids(self):
        """Test that post_save signal correctly updates Redis when model has session_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            session_ids=["session1", "session2"],
            pipelines=["analytics", "session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "session_id": "session1", "pipelines": ["analytics", "session_recordings"]},
            {"token": "test_token", "session_id": "session2", "pipelines": ["analytics", "session_recordings"]},
        ]
        assert sorted(data, key=lambda x: x["session_id"]) == sorted(expected_entries, key=lambda x: x["session_id"])

    def test_post_save_signal_with_both_distinct_ids_and_session_ids(self):
        """Test that post_save signal correctly updates Redis when model has both distinct_ids and session_ids (OR logic)"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["user1", "user2"],
            session_ids=["session1", "session2"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 4  # 2 distinct_ids + 2 session_ids

        expected_entries = [
            {"token": "test_token", "distinct_id": "user1", "pipelines": ["analytics"]},
            {"token": "test_token", "distinct_id": "user2", "pipelines": ["analytics"]},
            {"token": "test_token", "session_id": "session1", "pipelines": ["analytics"]},
            {"token": "test_token", "session_id": "session2", "pipelines": ["analytics"]},
        ]

        def sort_key(x):
            return (x.get("distinct_id", ""), x.get("session_id", ""))

        assert sorted(data, key=sort_key) == sorted(expected_entries, key=sort_key)

    def test_update_config_session_ids(self):
        """Test that updating a config's session_ids correctly updates Redis cache"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            session_ids=["session1", "session2"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        config.session_ids = ["session2", "session3"]  # Remove session1, keep session2, add session3
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "session_id": "session2", "pipelines": ["analytics"]},
            {"token": "test_token", "session_id": "session3", "pipelines": ["analytics"]},
        ]
        assert sorted(data, key=lambda x: x["session_id"]) == sorted(expected_entries, key=lambda x: x["session_id"])
        assert "session1" not in [entry.get("session_id") for entry in data]

    def test_update_config_remove_all_session_ids(self):
        """Test that removing all session_ids correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            session_ids=["session1", "session2"],
            pipelines=["analytics"],
        )

        config.session_ids = []
        config.save()

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "test_token", "pipelines": ["analytics"]}]

    def test_update_config_add_session_ids(self):
        """Test that adding session_ids to a config without them correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token", restriction_type=RestrictionType.SKIP_PERSON_PROCESSING, pipelines=["analytics"]
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "test_token", "pipelines": ["analytics"]}]

        config.session_ids = ["session1", "session2"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        expected_entries = [
            {"token": "test_token", "session_id": "session1", "pipelines": ["analytics"]},
            {"token": "test_token", "session_id": "session2", "pipelines": ["analytics"]},
        ]
        assert sorted(data, key=lambda x: x.get("session_id", "")) == sorted(
            expected_entries, key=lambda x: x.get("session_id", "")
        )
        # Verify the token-only entry was removed
        assert {"token": "test_token", "pipelines": ["analytics"]} not in data

    def test_transition_from_distinct_ids_to_session_ids(self):
        """Test that changing from distinct_ids to session_ids correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["user1", "user2"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2
        assert all("distinct_id" in entry for entry in data)

        # Change to session_ids
        config.distinct_ids = []
        config.session_ids = ["session1", "session2"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2
        assert all("session_id" in entry for entry in data)
        assert all("distinct_id" not in entry for entry in data)

    def test_post_save_signal_with_event_names(self):
        """Test that post_save signal correctly updates Redis when model has event_names"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            event_names=["$pageview", "$autocapture"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "event_name": "$pageview", "pipelines": ["analytics"]},
            {"token": "test_token", "event_name": "$autocapture", "pipelines": ["analytics"]},
        ]
        assert sorted(data, key=lambda x: x["event_name"]) == sorted(expected_entries, key=lambda x: x["event_name"])

    def test_post_save_signal_with_event_uuids(self):
        """Test that post_save signal correctly updates Redis when model has event_uuids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            event_uuids=["uuid-123", "uuid-456"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "event_uuid": "uuid-123", "pipelines": ["analytics"]},
            {"token": "test_token", "event_uuid": "uuid-456", "pipelines": ["analytics"]},
        ]
        assert sorted(data, key=lambda x: x["event_uuid"]) == sorted(expected_entries, key=lambda x: x["event_uuid"])

    def test_post_save_signal_with_all_filter_types(self):
        """Test that post_save signal correctly updates Redis when model has all filter types (OR logic)"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["user1"],
            session_ids=["session1"],
            event_names=["$pageview"],
            event_uuids=["uuid-123"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 4

        expected_entries = [
            {"token": "test_token", "distinct_id": "user1", "pipelines": ["analytics"]},
            {"token": "test_token", "session_id": "session1", "pipelines": ["analytics"]},
            {"token": "test_token", "event_name": "$pageview", "pipelines": ["analytics"]},
            {"token": "test_token", "event_uuid": "uuid-123", "pipelines": ["analytics"]},
        ]

        def sort_key(x):
            return (
                x.get("distinct_id", ""),
                x.get("session_id", ""),
                x.get("event_name", ""),
                x.get("event_uuid", ""),
            )

        assert sorted(data, key=sort_key) == sorted(expected_entries, key=sort_key)

    def test_update_config_event_names(self):
        """Test that updating a config's event_names correctly updates Redis cache"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            event_names=["$pageview", "$autocapture"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        config.event_names = ["$autocapture", "$click"]  # Remove $pageview, keep $autocapture, add $click
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "event_name": "$autocapture", "pipelines": ["analytics"]},
            {"token": "test_token", "event_name": "$click", "pipelines": ["analytics"]},
        ]
        assert sorted(data, key=lambda x: x["event_name"]) == sorted(expected_entries, key=lambda x: x["event_name"])
        assert "$pageview" not in [entry.get("event_name") for entry in data]

    def test_redirect_to_dlq_restriction_type(self):
        """Test that REDIRECT_TO_DLQ restriction type can be created and syncs to Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.REDIRECT_TO_DLQ,
            pipelines=["analytics"],
        )

        assert config.restriction_type == RestrictionType.REDIRECT_TO_DLQ
        assert config.get_redis_key() == f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.REDIRECT_TO_DLQ}"

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert data == [{"token": "test_token", "pipelines": ["analytics"]}]

    def test_redirect_to_dlq_with_distinct_ids(self):
        """Test REDIRECT_TO_DLQ restriction type with distinct_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.REDIRECT_TO_DLQ,
            distinct_ids=["user1", "user2"],
            pipelines=["analytics", "session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "distinct_id": "user1", "pipelines": ["analytics", "session_recordings"]},
            {"token": "test_token", "distinct_id": "user2", "pipelines": ["analytics", "session_recordings"]},
        ]
        assert sorted(data, key=lambda x: x["distinct_id"]) == sorted(expected_entries, key=lambda x: x["distinct_id"])

    def test_redirect_to_dlq_with_session_ids(self):
        """Test REDIRECT_TO_DLQ restriction type with session_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.REDIRECT_TO_DLQ,
            session_ids=["session1", "session2"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "session_id": "session1", "pipelines": ["analytics"]},
            {"token": "test_token", "session_id": "session2", "pipelines": ["analytics"]},
        ]
        assert sorted(data, key=lambda x: x["session_id"]) == sorted(expected_entries, key=lambda x: x["session_id"])

    def test_redirect_to_dlq_with_event_names(self):
        """Test REDIRECT_TO_DLQ restriction type with event_names"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.REDIRECT_TO_DLQ,
            event_names=["$pageview", "$autocapture"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        assert redis_data is not None

        data = json.loads(redis_data if redis_data is not None else b"[]")
        assert len(data) == 2

        expected_entries = [
            {"token": "test_token", "event_name": "$pageview", "pipelines": ["analytics"]},
            {"token": "test_token", "event_name": "$autocapture", "pipelines": ["analytics"]},
        ]
        assert sorted(data, key=lambda x: x["event_name"]) == sorted(expected_entries, key=lambda x: x["event_name"])

    def test_redirect_to_dlq_delete_removes_from_redis(self):
        """Test that deleting a REDIRECT_TO_DLQ config removes it from Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.REDIRECT_TO_DLQ,
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        assert self.redis_client.get(redis_key) is not None

        config.delete()

        assert self.redis_client.get(redis_key) is None
