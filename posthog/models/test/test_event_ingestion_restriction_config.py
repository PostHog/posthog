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

        self.assertEqual(config.token, "test_token")
        self.assertEqual(config.restriction_type, RestrictionType.SKIP_PERSON_PROCESSING)
        self.assertEqual(config.distinct_ids, ["id1", "id2"])
        self.assertEqual(config.pipelines, ["analytics"])
        self.assertEqual(
            config.get_redis_key(), f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.SKIP_PERSON_PROCESSING}"
        )

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
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 2)

        expected_entries = [
            {"token": "test_token", "distinct_id": "id1", "pipelines": ["analytics", "session_recordings"]},
            {"token": "test_token", "distinct_id": "id2", "pipelines": ["analytics", "session_recordings"]},
        ]
        self.assertEqual(
            sorted(data, key=lambda x: x["distinct_id"]), sorted(expected_entries, key=lambda x: x["distinct_id"])
        )

    def test_post_save_signal_without_distinct_ids(self):
        """Test that post_save signal correctly updates Redis when model has no distinct_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
            pipelines=["analytics"],
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "test_token", "pipelines": ["analytics"]}])

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
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 3)

        expected_entries = [
            {"token": "existing_token", "distinct_id": "existing_id", "pipelines": ["session_recordings"]},
            {"token": "test_token", "distinct_id": "id1", "pipelines": ["analytics"]},
            {"token": "test_token", "distinct_id": "id2", "pipelines": ["analytics"]},
        ]

        def sort_key(x):
            return (x["token"], x.get("distinct_id", ""))

        self.assertEqual(sorted(data, key=sort_key), sorted(expected_entries, key=sort_key))

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
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "other_token", "pipelines": ["analytics"]}])

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
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "other_token", "pipelines": ["analytics", "session_recordings"]}])

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
        self.assertEqual(len(data), 2)

        config.distinct_ids = ["id2", "id3"]  # Remove id1, keep id2, add id3
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 2)

        expected_entries = [
            {"token": "test_token", "distinct_id": "id2", "pipelines": ["analytics"]},
            {"token": "test_token", "distinct_id": "id3", "pipelines": ["analytics"]},
        ]
        self.assertEqual(
            sorted(data, key=lambda x: x["distinct_id"]), sorted(expected_entries, key=lambda x: x["distinct_id"])
        )
        self.assertNotIn("id1", [entry.get("distinct_id") for entry in data])

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
        self.assertEqual(data, [{"token": "test_token", "pipelines": ["analytics"]}])
        self.assertNotIn("id1", [entry.get("distinct_id", "") for entry in data])
        self.assertNotIn("id2", [entry.get("distinct_id", "") for entry in data])

    def test_update_config_add_distinct_ids(self):
        """Test that adding distinct_ids to a config without them correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token", restriction_type=RestrictionType.SKIP_PERSON_PROCESSING, pipelines=["analytics"]
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "test_token", "pipelines": ["analytics"]}])

        config.distinct_ids = ["id1", "id2"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        expected_entries = [
            {"token": "test_token", "distinct_id": "id1", "pipelines": ["analytics"]},
            {"token": "test_token", "distinct_id": "id2", "pipelines": ["analytics"]},
        ]
        self.assertEqual(
            sorted(data, key=lambda x: x.get("distinct_id", "")),
            sorted(expected_entries, key=lambda x: x.get("distinct_id", "")),
        )
        # Verify the token-only entry was removed
        self.assertNotIn({"token": "test_token", "pipelines": ["analytics"]}, data)

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

        self.assertEqual(data, [{"token": "test_token", "pipelines": ["session_recordings"]}])

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
        self.assertEqual(data, [{"token": "test_token", "pipelines": ["analytics"]}])

        config.pipelines = ["session_recordings"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "test_token", "pipelines": ["session_recordings"]}])

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
        self.assertEqual(
            sorted(data, key=lambda x: x["distinct_id"]), sorted(expected_entries, key=lambda x: x["distinct_id"])
        )
