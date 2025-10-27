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
            token="test_token", restriction_type=RestrictionType.SKIP_PERSON_PROCESSING, distinct_ids=["id1", "id2"]
        )

        self.assertEqual(config.token, "test_token")
        self.assertEqual(config.restriction_type, RestrictionType.SKIP_PERSON_PROCESSING)
        self.assertEqual(config.distinct_ids, ["id1", "id2"])
        self.assertEqual(config.analytics, True)
        self.assertEqual(config.session_recordings, False)
        self.assertEqual(
            config.get_redis_key(), f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.SKIP_PERSON_PROCESSING}"
        )

    def test_post_save_signal_with_distinct_ids(self):
        """Test that post_save signal correctly updates Redis when model has distinct_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token", restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION, distinct_ids=["id1", "id2"]
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 2)

        expected_entries = [
            {"token": "test_token", "distinct_id": "id1", "analytics": True, "session_recordings": False},
            {"token": "test_token", "distinct_id": "id2", "analytics": True, "session_recordings": False},
        ]
        self.assertEqual(
            sorted(data, key=lambda x: x["distinct_id"]), sorted(expected_entries, key=lambda x: x["distinct_id"])
        )

    def test_post_save_signal_without_distinct_ids(self):
        """Test that post_save signal correctly updates Redis when model has no distinct_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "test_token", "analytics": True, "session_recordings": False}])

    def test_post_save_signal_with_existing_data(self):
        """Test that post_save signal correctly merges with existing Redis data"""
        EventIngestionRestrictionConfig.objects.create(
            token="existing_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["existing_id"],
        )

        second_config = EventIngestionRestrictionConfig.objects.create(
            token="test_token", restriction_type=RestrictionType.SKIP_PERSON_PROCESSING, distinct_ids=["id1", "id2"]
        )

        redis_key = second_config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(len(data), 3)

        expected_entries = [
            {"token": "existing_token", "distinct_id": "existing_id", "analytics": True, "session_recordings": False},
            {"token": "test_token", "distinct_id": "id1", "analytics": True, "session_recordings": False},
            {"token": "test_token", "distinct_id": "id2", "analytics": True, "session_recordings": False},
        ]

        def sort_key(x):
            return (x["token"], x.get("distinct_id", ""))

        self.assertEqual(sorted(data, key=sort_key), sorted(expected_entries, key=sort_key))

    def test_post_delete_signal_with_distinct_ids(self):
        """Test that post_delete signal correctly updates Redis when deleting a model with distinct_ids"""
        EventIngestionRestrictionConfig.objects.create(
            token="other_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
        )

        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token", restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION, distinct_ids=["id1", "id2"]
        )

        config.delete()

        redis_key = f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.DROP_EVENT_FROM_INGESTION}"
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "other_token", "analytics": True, "session_recordings": False}])

    def test_post_delete_signal_without_distinct_ids(self):
        """Test that post_delete signal correctly updates Redis when deleting a model without distinct_ids"""
        EventIngestionRestrictionConfig.objects.create(
            token="other_token",
            restriction_type=RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
        )

        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
        )

        config.delete()

        redis_key = f"{DYNAMIC_CONFIG_REDIS_KEY_PREFIX}:{RestrictionType.FORCE_OVERFLOW_FROM_INGESTION}"
        redis_data = self.redis_client.get(redis_key)
        self.assertIsNotNone(redis_data)

        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "other_token", "analytics": True, "session_recordings": False}])

    def test_post_delete_signal_removes_key_when_empty(self):
        """Test that post_delete signal removes Redis key when no data remains"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
        )

        redis_key = config.get_redis_key()
        self.assertIsNotNone(self.redis_client.get(redis_key))

        config.delete()

        self.assertIsNone(self.redis_client.get(redis_key))

    def test_update_config_distinct_ids(self):
        """Test that updating a config's distinct_ids correctly updates Redis cache"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token", restriction_type=RestrictionType.SKIP_PERSON_PROCESSING, distinct_ids=["id1", "id2"]
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
            {"token": "test_token", "distinct_id": "id2", "analytics": True, "session_recordings": False},
            {"token": "test_token", "distinct_id": "id3", "analytics": True, "session_recordings": False},
        ]
        self.assertEqual(
            sorted(data, key=lambda x: x["distinct_id"]), sorted(expected_entries, key=lambda x: x["distinct_id"])
        )
        self.assertNotIn("id1", [entry.get("distinct_id") for entry in data])

    def test_update_config_remove_all_distinct_ids(self):
        """Test that removing all distinct_ids correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token", restriction_type=RestrictionType.SKIP_PERSON_PROCESSING, distinct_ids=["id1", "id2"]
        )

        config.distinct_ids = []
        config.save()

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "test_token", "analytics": True, "session_recordings": False}])
        self.assertNotIn("id1", [entry.get("distinct_id", "") for entry in data])
        self.assertNotIn("id2", [entry.get("distinct_id", "") for entry in data])

    def test_update_config_add_distinct_ids(self):
        """Test that adding distinct_ids to a config without them correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token", restriction_type=RestrictionType.SKIP_PERSON_PROCESSING
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "test_token", "analytics": True, "session_recordings": False}])

        config.distinct_ids = ["id1", "id2"]
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        expected_entries = [
            {"token": "test_token", "distinct_id": "id1", "analytics": True, "session_recordings": False},
            {"token": "test_token", "distinct_id": "id2", "analytics": True, "session_recordings": False},
        ]
        self.assertEqual(
            sorted(data, key=lambda x: x.get("distinct_id", "")),
            sorted(expected_entries, key=lambda x: x.get("distinct_id", "")),
        )
        # Verify the token-only entry was removed
        self.assertNotIn({"token": "test_token", "analytics": True, "session_recordings": False}, data)

    def test_pipeline_fields_in_redis(self):
        """Test that analytics and session_recordings fields are correctly stored in Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            analytics=False,
            session_recordings=True,
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")

        self.assertEqual(data, [{"token": "test_token", "analytics": False, "session_recordings": True}])

    def test_update_pipeline_fields(self):
        """Test that updating pipeline fields correctly updates Redis"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.DROP_EVENT_FROM_INGESTION,
            analytics=True,
            session_recordings=False,
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "test_token", "analytics": True, "session_recordings": False}])

        config.analytics = False
        config.session_recordings = True
        config.save()

        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")
        self.assertEqual(data, [{"token": "test_token", "analytics": False, "session_recordings": True}])

    def test_pipeline_fields_with_distinct_ids(self):
        """Test that pipeline fields work correctly with distinct_ids"""
        config = EventIngestionRestrictionConfig.objects.create(
            token="test_token",
            restriction_type=RestrictionType.SKIP_PERSON_PROCESSING,
            distinct_ids=["id1", "id2"],
            analytics=False,
            session_recordings=True,
        )

        redis_key = config.get_redis_key()
        redis_data = self.redis_client.get(redis_key)
        data = json.loads(redis_data if redis_data is not None else b"[]")

        expected_entries = [
            {"token": "test_token", "distinct_id": "id1", "analytics": False, "session_recordings": True},
            {"token": "test_token", "distinct_id": "id2", "analytics": False, "session_recordings": True},
        ]
        self.assertEqual(
            sorted(data, key=lambda x: x["distinct_id"]), sorted(expected_entries, key=lambda x: x["distinct_id"])
        )
