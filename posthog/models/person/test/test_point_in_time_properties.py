"""
Tests for point-in-time person properties building functionality.
"""

import json
from datetime import UTC, datetime
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized_class

from posthog.models.person.point_in_time_properties import (
    build_person_properties_at_time,
    get_person_and_distinct_ids_for_identifier,
)
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.test_helpers import PersonhogTestMixin


class TestPointInTimeProperties(TestCase):
    def test_build_person_properties_at_time_validation(self):
        """Test input validation for build_person_properties_at_time."""
        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Test invalid team_id
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(0, timestamp, ["user123"])
        self.assertIn("team_id must be a positive integer", str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(-1, timestamp, ["user123"])
        self.assertIn("team_id must be a positive integer", str(cm.exception))

        # Test invalid timestamp
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(1, cast(datetime, "2023-01-01"), ["user123"])
        self.assertIn("timestamp must be a datetime object", str(cm.exception))

        # Test invalid distinct_ids (empty list)
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(1, timestamp, [])
        self.assertIn("distinct_ids must be a non-empty list", str(cm.exception))

        # Test invalid distinct_ids (not a list)
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(1, timestamp, "not_a_list")  # type: ignore[arg-type]
        self.assertIn("distinct_ids must be a non-empty list", str(cm.exception))

        # Test invalid distinct_ids (contains empty string)
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(1, timestamp, ["user123", ""])
        self.assertIn("All distinct_ids must be non-empty strings", str(cm.exception))

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_empty_result(self, mock_sync_execute):
        """Test building properties when no events exist."""
        mock_sync_execute.return_value = []

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"])

        self.assertEqual(result, {})
        mock_sync_execute.assert_called_once()

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_single_set(self, mock_sync_execute):
        """Test building properties with a single $set event."""
        # Mock ClickHouse response with a single $set event
        properties = {"$set": {"name": "John Doe", "email": "john@example.com"}}
        # ClickHouse toJSONString() returns double-encoded JSON
        double_encoded_json = json.dumps(json.dumps(properties))
        mock_sync_execute.return_value = [(double_encoded_json, datetime(2023, 1, 1, 10, 0, 0), "$set")]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"])

        expected = {"name": "John Doe", "email": "john@example.com"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_multiple_sets(self, mock_sync_execute):
        """Test building properties with multiple $set events applied chronologically."""
        # Mock ClickHouse response with multiple $set events
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            (json.dumps(json.dumps({"$set": {"name": "John", "age": 25}})), datetime(2023, 1, 1, 9, 0, 0), "$set"),
            (
                json.dumps(json.dumps({"$set": {"name": "John Doe", "location": "SF"}})),
                datetime(2023, 1, 1, 10, 0, 0),
                "$pageview",
            ),
            (json.dumps(json.dumps({"$set": {"age": 26}})), datetime(2023, 1, 1, 11, 0, 0), "$set"),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"])

        expected = {"name": "John Doe", "age": 26, "location": "SF"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_malformed_json(self, mock_sync_execute):
        """Test handling of malformed JSON in event properties."""
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            ("invalid json", datetime(2023, 1, 1, 9, 0, 0), "$set"),
            (json.dumps(json.dumps({"$set": {"name": "John"}})), datetime(2023, 1, 1, 10, 0, 0), "$set"),
            (json.dumps(json.dumps({"no_set_key": "value"})), datetime(2023, 1, 1, 11, 0, 0), "$pageview"),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"])

        # Should only get the valid $set event
        expected = {"name": "John"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_clickhouse_error(self, mock_sync_execute):
        """Test handling of ClickHouse query errors."""
        mock_sync_execute.side_effect = Exception("ClickHouse connection failed")

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)

        with self.assertRaises(Exception) as cm:
            build_person_properties_at_time(1, timestamp, ["user123"])

        self.assertIn("Failed to query ClickHouse events", str(cm.exception))


class TestPointInTimePropertiesWithSetOnce(TestCase):
    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_with_set_once_basic(self, mock_sync_execute):
        """Test $set_once operations only set properties that don't exist."""
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            (json.dumps(json.dumps({"$set": {"name": "John"}})), datetime(2023, 1, 1, 9, 0, 0), "$set"),
            (
                json.dumps(json.dumps({"$set_once": {"name": "Jane", "email": "jane@example.com"}})),
                datetime(2023, 1, 1, 10, 0, 0),
                "$set_once",
            ),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"], include_set_once=True)

        # name should remain "John" (not overwritten by $set_once)
        # email should be set by $set_once since it didn't exist
        expected = {"name": "John", "email": "jane@example.com"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_with_set_once_order_matters(self, mock_sync_execute):
        """Test that order of $set and $set_once operations matters."""
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            (
                json.dumps(json.dumps({"$set_once": {"name": "Jane", "email": "jane@example.com"}})),
                datetime(2023, 1, 1, 9, 0, 0),
                "$set_once",
            ),
            (json.dumps(json.dumps({"$set": {"name": "John"}})), datetime(2023, 1, 1, 10, 0, 0), "$set"),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"], include_set_once=True)

        # $set_once sets name first, then $set overwrites it
        expected = {"name": "John", "email": "jane@example.com"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_with_set_once_multiple_set_once(self, mock_sync_execute):
        """Test multiple $set_once operations - only first one should apply per property."""
        # ClickHouse toJSONString() returns double-encoded JSON
        mock_sync_execute.return_value = [
            (
                json.dumps(json.dumps({"$set_once": {"name": "First", "email": "first@example.com"}})),
                datetime(2023, 1, 1, 9, 0, 0),
                "$set_once",
            ),
            (
                json.dumps(json.dumps({"$set_once": {"name": "Second", "location": "SF"}})),
                datetime(2023, 1, 1, 10, 0, 0),
                "$set_once",
            ),
        ]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, ["user123"], include_set_once=True)

        # First $set_once should win for name, second should set location
        expected = {"name": "First", "email": "first@example.com", "location": "SF"}
        self.assertEqual(result, expected)

    @patch("posthog.models.person.point_in_time_properties.sync_execute")
    def test_build_person_properties_at_time_with_distinct_ids_direct(self, mock_sync_execute):
        """Test building properties using distinct_ids parameter directly."""
        # Mock ClickHouse response with a single $set event
        properties = {"$set": {"name": "Jane Doe", "email": "jane@example.com"}}
        # ClickHouse toJSONString() returns double-encoded JSON
        double_encoded_json = json.dumps(json.dumps(properties))
        mock_sync_execute.return_value = [(double_encoded_json, datetime(2023, 1, 1, 10, 0, 0), "$set")]

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = build_person_properties_at_time(1, timestamp, distinct_ids=["user123", "user456", "user789"])

        expected = {"name": "Jane Doe", "email": "jane@example.com"}
        self.assertEqual(result, expected)

        # Verify the query was called with all distinct_ids
        mock_sync_execute.assert_called_once()
        call_args = mock_sync_execute.call_args
        self.assertEqual(call_args[0][1]["distinct_ids"], ["user123", "user456", "user789"])


class TestGetPersonAndDistinctIdsForIdentifierValidation(SimpleTestCase):
    def test_both_params_raises(self):
        with self.assertRaises(ValueError, msg="Cannot provide both"):
            get_person_and_distinct_ids_for_identifier(1, distinct_id="d1", person_id="uuid1")

    def test_neither_param_raises(self):
        with self.assertRaises(ValueError, msg="Must provide either"):
            get_person_and_distinct_ids_for_identifier(1)

    def test_empty_distinct_id_raises(self):
        with self.assertRaises(ValueError, msg="non-empty string"):
            get_person_and_distinct_ids_for_identifier(1, distinct_id="")

    def test_empty_person_id_raises(self):
        with self.assertRaises(ValueError, msg="non-empty value"):
            get_person_and_distinct_ids_for_identifier(1, person_id="")


class TestGetPersonAndDistinctIdsForIdentifierPersonhog(SimpleTestCase):
    def test_lookup_by_distinct_id(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="00000000-0000-0000-0000-000000000042",
                properties={"email": "test@example.com"},
                distinct_ids=["d1", "d2"],
            )

            person, dids = get_person_and_distinct_ids_for_identifier(1, distinct_id="d1")

            assert person is not None
            assert str(person.uuid) == "00000000-0000-0000-0000-000000000042"
            assert person.properties == {"email": "test@example.com"}
            assert set(dids) == {"d1", "d2"}
            fake.assert_called("get_person_by_distinct_id")
            fake.assert_called("get_distinct_ids_for_person")

    def test_lookup_by_person_id(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="00000000-0000-0000-0000-000000000042",
                properties={"name": "Test"},
                distinct_ids=["d1"],
            )

            person, dids = get_person_and_distinct_ids_for_identifier(
                1, person_id="00000000-0000-0000-0000-000000000042"
            )

            assert person is not None
            assert str(person.uuid) == "00000000-0000-0000-0000-000000000042"
            assert dids == ["d1"]
            fake.assert_called("get_person_by_uuid")
            fake.assert_called("get_distinct_ids_for_person")

    def test_person_not_found_returns_none(self):
        with fake_personhog_client() as fake:
            person, dids = get_person_and_distinct_ids_for_identifier(1, distinct_id="unknown")

            assert person is None
            assert dids == []
            fake.assert_called("get_person_by_distinct_id")

    def test_distinct_ids_from_personhog_used_directly(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1,
                person_id=42,
                uuid="00000000-0000-0000-0000-000000000042",
                distinct_ids=["a", "b", "c"],
            )

            person, dids = get_person_and_distinct_ids_for_identifier(1, distinct_id="a")

            assert person is not None
            assert set(dids) == {"a", "b", "c"}

    def test_cross_team_isolation(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=2,
                person_id=42,
                uuid="00000000-0000-0000-0000-000000000042",
                distinct_ids=["d1"],
            )

            person, dids = get_person_and_distinct_ids_for_identifier(1, distinct_id="d1")

            assert person is None
            assert dids == []


@parameterized_class(("personhog",), [(False,), (True,)])
class TestGetPersonAndDistinctIdsForIdentifierIntegration(PersonhogTestMixin, BaseTest):
    def test_lookup_by_distinct_id(self):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["d1", "d2"],
            properties={"email": "test@example.com"},
        )

        result_person, result_dids = get_person_and_distinct_ids_for_identifier(self.team.pk, distinct_id="d1")

        assert result_person is not None
        assert str(result_person.uuid) == str(person.uuid)
        assert result_person.properties == {"email": "test@example.com"}
        assert set(result_dids) == {"d1", "d2"}
        self._assert_personhog_called("get_person_by_distinct_id")

    def test_lookup_by_person_id(self):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["d1"],
            properties={"name": "Test"},
        )

        result_person, result_dids = get_person_and_distinct_ids_for_identifier(
            self.team.pk, person_id=str(person.uuid)
        )

        assert result_person is not None
        assert str(result_person.uuid) == str(person.uuid)
        assert result_dids == ["d1"]
        self._assert_personhog_called("get_person_by_uuid")

    def test_person_not_found(self):
        result_person, result_dids = get_person_and_distinct_ids_for_identifier(self.team.pk, distinct_id="unknown")

        assert result_person is None
        assert result_dids == []

    def test_cross_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        self._seed_person(team=other_team, distinct_ids=["shared_did"])

        result_person, result_dids = get_person_and_distinct_ids_for_identifier(self.team.pk, distinct_id="shared_did")

        assert result_person is None
        assert result_dids == []
