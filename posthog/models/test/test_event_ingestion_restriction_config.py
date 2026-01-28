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
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id1", "id2"],
            pipelines=["analytics"],
        )

        self.assertEqual(config.token, "test_token")
        self.assertEqual(config.restriction_type, RestrictionType.SKIP_PERSON_PROCESSING)
        self.assertEqual(config.distinct_ids, ["id1", "id2"])
        self.assertEqual(config.pipelines, ["analytics"])
        self.assertEqual(
            config.get_redis_key(), f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.SKIP_PERSON_PROCESSING}"
        )

    def test_post_save_signal_generates_v2_format(self):
        """Test that post_save signal generates v2 format with arrays"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            distinct_ids=["id1", "id2"],
            pipelines=["analytics", "session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 1)

        expected_entry = {
            "version": 2,
            "token": "test_token",
            "pipelines": ["analytics", "session_recordings"],
            "distinct_ids": ["id1", "id2"],
            "session_ids": [],
            "event_names": [],
            "event_uuids": [],
        }
        self.assertEqual(data[0], expected_entry)

    def test_post_save_signal_without_filters(self):
        """Test v2 format when model has no specific filters (applies to all events)"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        expected_entry = {
            "version": 2,
            "token": "test_token",
            "pipelines": ["analytics"],
            "distinct_ids": [],
            "session_ids": [],
            "event_names": [],
            "event_uuids": [],
        }
        self.assertEqual(data, [expected_entry])

    def test_post_save_signal_with_multiple_configs(self):
        """Test that multiple configs generate separate v2 entries"""
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
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 2)

        data_by_token = {entry["token"]: entry for entry in data}

        self.assertEqual(
            data_by_token["existing_token"],
            {
                "version": 2,
                "token": "existing_token",
                "pipelines": ["session_recordings"],
                "distinct_ids": ["existing_id"],
                "session_ids": [],
                "event_names": [],
                "event_uuids": [],
            },
        )
        self.assertEqual(
            data_by_token["test_token"],
            {
                "version": 2,
                "token": "test_token",
                "pipelines": ["analytics"],
                "distinct_ids": ["id1", "id2"],
                "session_ids": [],
                "event_names": [],
                "event_uuids": [],
            },
        )

    def test_post_delete_signal(self):
        """Test that post_delete signal correctly updates Redis"""
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
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(
            data,
            [
                {
                    "version": 2,
                    "token": "other_token",
                    "pipelines": ["analytics"],
                    "distinct_ids": [],
                    "session_ids": [],
                    "event_names": [],
                    "event_uuids": [],
                }
            ],
        )

    def test_post_delete_signal_removes_key_when_empty(self):
        """Test that post_delete signal removes Redis key when no data remains"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        self.assertIsNotNone(self.redis_client.get(redis_key))

        config.delete()

        self.assertIsNone(self.redis_client.get(redis_key))

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
        self.assertEqual(data[0]["distinct_ids"], ["id1", "id2"])

        config.distinct_ids = ["id2", "id3"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["distinct_ids"], ["id2", "id3"])

    def test_update_config_remove_all_distinct_ids(self):
        """Test that removing all distinct_ids results in empty array (token-level restriction)"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id1", "id2"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data[0]["distinct_ids"], ["id1", "id2"])

        config.distinct_ids = []
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")

        self.assertEqual(
            data,
            [
                {
                    "version": 2,
                    "token": "test_token",
                    "pipelines": ["analytics"],
                    "distinct_ids": [],
                    "session_ids": [],
                    "event_names": [],
                    "event_uuids": [],
                }
            ],
        )

    def test_update_config_add_distinct_ids(self):
        """Test that adding distinct_ids to a token-level restriction correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data[0]["distinct_ids"], [])

        config.distinct_ids = ["id1", "id2"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")

        self.assertEqual(
            data,
            [
                {
                    "version": 2,
                    "token": "test_token",
                    "pipelines": ["analytics"],
                    "distinct_ids": ["id1", "id2"],
                    "session_ids": [],
                    "event_names": [],
                    "event_uuids": [],
                }
            ],
        )

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

        self.assertEqual(data[0]["pipelines"], ["session_recordings"])

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
        self.assertEqual(data[0]["pipelines"], ["analytics"])

        config.pipelines = ["session_recordings"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data[0]["pipelines"], ["session_recordings"])

    def test_regenerate_redis_removes_deleted_entries(self):
        """Test that deleting a config regenerates Redis and removes only that config's entries"""
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
        self.assertEqual(len(data), 2)

        config1.delete()

        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(
            data,
            [
                {
                    "version": 2,
                    "token": "test_token_2",
                    "pipelines": ["session_recordings"],
                    "distinct_ids": [],
                    "session_ids": [],
                    "event_names": [],
                    "event_uuids": [],
                }
            ],
        )

    def test_regenerate_redis_with_multiple_configs_different_pipelines(self):
        """Test that each restriction type has its own Redis key"""
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

        redis_key1 = config1.get_redis_key()
        redis_data1 = self.redis_client.get(redis_key1)
        data1 = json.loads(redis_data1 if redis_data1 is not None else b"[]")
        self.assertEqual(
            data1,
            [
                {
                    "version": 2,
                    "token": "test_token",
                    "pipelines": ["analytics"],
                    "distinct_ids": [],
                    "session_ids": [],
                    "event_names": [],
                    "event_uuids": [],
                }
            ],
        )

        redis_key2 = config2.get_redis_key()
        redis_data2 = self.redis_client.get(redis_key2)
        data2 = json.loads(redis_data2 if redis_data2 is not None else b"[]")
        self.assertEqual(
            data2,
            [
                {
                    "version": 2,
                    "token": "test_token",
                    "pipelines": ["session_recordings"],
                    "distinct_ids": [],
                    "session_ids": [],
                    "event_names": [],
                    "event_uuids": [],
                }
            ],
        )

        config1.delete()

        redis_data1 = self.redis_client.get(redis_key1)
        self.assertIsNone(redis_data1)

        redis_data2 = self.redis_client.get(redis_key2)
        self.assertIsNotNone(redis_data2)

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

        config1.pipelines = ["analytics", "session_recordings"]
        config1.save()

        redis_key = config1.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")

        self.assertEqual(len(data), 2)

        data_by_token = {entry["token"]: entry for entry in data}

        self.assertEqual(
            data_by_token["test_token_1"],
            {
                "version": 2,
                "token": "test_token_1",
                "pipelines": ["analytics", "session_recordings"],
                "distinct_ids": ["id1"],
                "session_ids": [],
                "event_names": [],
                "event_uuids": [],
            },
        )
        self.assertEqual(
            data_by_token["test_token_2"],
            {
                "version": 2,
                "token": "test_token_2",
                "pipelines": ["session_recordings"],
                "distinct_ids": ["id2"],
                "session_ids": [],
                "event_names": [],
                "event_uuids": [],
            },
        )

    def test_post_save_signal_with_session_ids(self):
        """Test v2 format with session_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            session_ids=["session1", "session2"],
            pipelines=["analytics", "session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 1)

        expected_entry = {
            "version": 2,
            "token": "test_token",
            "pipelines": ["analytics", "session_recordings"],
            "distinct_ids": [],
            "session_ids": ["session1", "session2"],
            "event_names": [],
            "event_uuids": [],
        }
        self.assertEqual(data[0], expected_entry)

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
        self.assertEqual(data[0]["session_ids"], ["session1", "session2"])

        config.session_ids = ["session2", "session3"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["session_ids"], ["session2", "session3"])

    def test_update_config_remove_all_session_ids(self):
        """Test that removing all session_ids results in empty array"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            session_ids=["session1", "session2"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data[0]["session_ids"], ["session1", "session2"])

        config.session_ids = []
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data[0]["session_ids"], [])

    def test_update_config_add_session_ids(self):
        """Test that adding session_ids to a config without them correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data[0]["session_ids"], [])

        config.session_ids = ["session1", "session2"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data[0]["session_ids"], ["session1", "session2"])

    def test_post_save_signal_with_event_names(self):
        """Test v2 format with event_names"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            event_names=["$pageview", "$autocapture"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["event_names"], ["$pageview", "$autocapture"])

    def test_post_save_signal_with_event_uuids(self):
        """Test v2 format with event_uuids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            event_uuids=["uuid-123", "uuid-456"],
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["event_uuids"], ["uuid-123", "uuid-456"])

    def test_post_save_signal_with_all_filter_types(self):
        """Test v2 format with all filter types (AND logic between types)"""
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
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 1)

        expected_entry = {
            "version": 2,
            "token": "test_token",
            "pipelines": ["analytics"],
            "distinct_ids": ["user1"],
            "session_ids": ["session1"],
            "event_names": ["$pageview"],
            "event_uuids": ["uuid-123"],
        }
        self.assertEqual(data[0], expected_entry)

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
        self.assertEqual(data[0]["event_names"], ["$pageview", "$autocapture"])

        config.event_names = ["$autocapture", "$click"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["event_names"], ["$autocapture", "$click"])

    def test_redirect_to_dlq_restriction_type(self):
        """Test that REDIRECT_TO_DLQ restriction type generates v2 format"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.REDIRECT_TO_DLQ,
            pipelines=["analytics"],
        )

        self.assertEqual(config.restriction_type, RestrictionType.REDIRECT_TO_DLQ)
        self.assertEqual(config.get_redis_key(), f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.REDIRECT_TO_DLQ}")

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        expected_entry = {
            "version": 2,
            "token": "test_token",
            "pipelines": ["analytics"],
            "distinct_ids": [],
            "session_ids": [],
            "event_names": [],
            "event_uuids": [],
        }
        self.assertEqual(data, [expected_entry])

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
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["distinct_ids"], ["user1", "user2"])

    def test_redirect_to_dlq_session_recordings_by_session_id(self):
        """Test redirecting session recordings to DLQ by session_id - real-world use case"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.REDIRECT_TO_DLQ,
            session_ids=["large-session-1", "large-session-2"],
            pipelines=["session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(
            data,
            [
                {
                    "version": 2,
                    "token": "test_token",
                    "pipelines": ["session_recordings"],
                    "distinct_ids": [],
                    "session_ids": ["large-session-1", "large-session-2"],
                    "event_names": [],
                    "event_uuids": [],
                }
            ],
        )

    def test_drop_session_recordings_by_session_id(self):
        """Test dropping specific session recordings by session_id - real-world use case"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            session_ids=["problematic-session-1", "problematic-session-2"],
            pipelines=["session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(
            data,
            [
                {
                    "version": 2,
                    "token": "test_token",
                    "pipelines": ["session_recordings"],
                    "distinct_ids": [],
                    "session_ids": ["problematic-session-1", "problematic-session-2"],
                    "event_names": [],
                    "event_uuids": [],
                }
            ],
        )

    def test_drop_events_by_session_id_and_event_name(self):
        """Test dropping events matching both session_id AND event_name (AND logic)"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            session_ids=["session-1", "session-2"],
            event_names=["$snapshot", "$replay_event"],
            pipelines=["session_recordings"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(
            data,
            [
                {
                    "version": 2,
                    "token": "test_token",
                    "pipelines": ["session_recordings"],
                    "distinct_ids": [],
                    "session_ids": ["session-1", "session-2"],
                    "event_names": ["$snapshot", "$replay_event"],
                    "event_uuids": [],
                }
            ],
        )
