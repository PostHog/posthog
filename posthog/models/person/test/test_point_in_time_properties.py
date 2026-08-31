"""
Tests for point-in-time person properties building functionality.
"""

import json
from datetime import UTC, datetime
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.schema import HogQLQueryResponse

from posthog.models.person.point_in_time_properties import (
    build_person_properties_at_time,
    get_person_and_distinct_ids_for_identifier,
)
from posthog.models.team import Team
from posthog.personhog_client.fake_client import fake_personhog_client, get_active_fake
from posthog.test.persons import create_person


def _prop_row(
    set_dict: dict | None = None,
    set_once_dict: dict | None = None,
    event: str = "$set",
) -> tuple:
    """Helper to build a property-update row matching the SELECT shape."""
    return (
        json.dumps(set_dict) if set_dict is not None else "",
        json.dumps(set_once_dict) if set_once_dict is not None else "",
        event,
    )


class TestPointInTimeProperties(SimpleTestCase):
    def setUp(self):
        self.team = Team(id=1)

    def test_build_person_properties_at_time_validation(self):
        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Test invalid timestamp
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(self.team, cast(datetime, "2023-01-01"), ["user123"])
        self.assertIn("timestamp must be a datetime object", str(cm.exception))

        # Test invalid distinct_ids (empty list)
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(self.team, timestamp, [])
        self.assertIn("distinct_ids must be a non-empty list", str(cm.exception))

        # Test invalid distinct_ids (not a list)
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(self.team, timestamp, "not_a_list")  # type: ignore[arg-type]
        self.assertIn("distinct_ids must be a non-empty list", str(cm.exception))

        # Test invalid distinct_ids (contains empty string)
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(self.team, timestamp, ["user123", ""])
        self.assertIn("All distinct_ids must be non-empty strings", str(cm.exception))

        # Invalid row_limit
        with self.assertRaises(ValueError) as cm:
            build_person_properties_at_time(self.team, timestamp, ["user123"], row_limit=0)
        self.assertIn("row_limit must be a positive integer", str(cm.exception))

    @patch("posthog.models.person.point_in_time_properties.execute_hogql_query")
    def test_build_person_properties_at_time_empty_result(self, mock_execute_hogql_query):
        """Zero rows means the person had no property activity at or before timestamp."""
        mock_execute_hogql_query.return_value = HogQLQueryResponse(results=[])

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        properties = build_person_properties_at_time(self.team, timestamp, ["user123"])

        self.assertEqual(properties, {})
        mock_execute_hogql_query.assert_called_once()

    @patch("posthog.models.person.point_in_time_properties.execute_hogql_query")
    def test_build_person_properties_at_time_single_set(self, mock_execute_hogql_query):
        mock_execute_hogql_query.return_value = HogQLQueryResponse(
            results=[
                _prop_row(set_dict={"name": "John Doe", "email": "john@example.com"}, event="$set"),
            ]
        )

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        properties = build_person_properties_at_time(self.team, timestamp, ["user123"])

        self.assertEqual(properties, {"name": "John Doe", "email": "john@example.com"})

    @patch("posthog.models.person.point_in_time_properties.execute_hogql_query")
    def test_build_person_properties_at_time_multiple_sets(self, mock_execute_hogql_query):
        mock_execute_hogql_query.return_value = HogQLQueryResponse(
            results=[
                _prop_row(set_dict={"name": "John", "age": 25}, event="$set"),
                _prop_row(set_dict={"name": "John Doe", "location": "SF"}, event="$pageview"),
                _prop_row(set_dict={"age": 26}, event="$set"),
            ]
        )

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        properties = build_person_properties_at_time(self.team, timestamp, ["user123"])

        self.assertEqual(properties, {"name": "John Doe", "age": 26, "location": "SF"})

    @patch("posthog.models.person.point_in_time_properties.execute_hogql_query")
    def test_build_person_properties_at_time_malformed_json(self, mock_execute_hogql_query):
        mock_execute_hogql_query.return_value = HogQLQueryResponse(
            results=[
                ("invalid json", "", "$set"),
                _prop_row(set_dict={"name": "John"}, event="$set"),
                ("", "", "$pageview"),
            ]
        )

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        properties = build_person_properties_at_time(self.team, timestamp, ["user123"])

        self.assertEqual(properties, {"name": "John"})


class TestPointInTimePropertiesWithSetOnce(SimpleTestCase):
    def setUp(self):
        self.team = Team(id=1)

    @patch("posthog.models.person.point_in_time_properties.execute_hogql_query")
    def test_build_person_properties_with_set_once_basic(self, mock_execute_hogql_query):
        """$set_once only sets properties that don't exist yet."""
        mock_execute_hogql_query.return_value = HogQLQueryResponse(
            results=[
                _prop_row(set_dict={"name": "John"}, event="$set"),
                _prop_row(set_once_dict={"name": "Jane", "email": "jane@example.com"}, event="$set_once"),
            ]
        )

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        properties = build_person_properties_at_time(self.team, timestamp, ["user123"], include_set_once=True)

        # name stays as "John" (not overwritten by $set_once); email is set by $set_once since it didn't exist
        self.assertEqual(properties, {"name": "John", "email": "jane@example.com"})

    @patch("posthog.models.person.point_in_time_properties.execute_hogql_query")
    def test_build_person_properties_with_set_once_order_matters(self, mock_execute_hogql_query):
        mock_execute_hogql_query.return_value = HogQLQueryResponse(
            results=[
                _prop_row(set_once_dict={"name": "Jane", "email": "jane@example.com"}, event="$set_once"),
                _prop_row(set_dict={"name": "John"}, event="$set"),
            ]
        )

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        properties = build_person_properties_at_time(self.team, timestamp, ["user123"], include_set_once=True)

        # $set_once sets name first, then $set overwrites it
        self.assertEqual(properties, {"name": "John", "email": "jane@example.com"})

    @patch("posthog.models.person.point_in_time_properties.execute_hogql_query")
    def test_build_person_properties_with_set_once_multiple_set_once(self, mock_execute_hogql_query):
        mock_execute_hogql_query.return_value = HogQLQueryResponse(
            results=[
                _prop_row(set_once_dict={"name": "First", "email": "first@example.com"}, event="$set_once"),
                _prop_row(set_once_dict={"name": "Second", "location": "SF"}, event="$set_once"),
            ]
        )

        timestamp = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        properties = build_person_properties_at_time(self.team, timestamp, ["user123"], include_set_once=True)

        self.assertEqual(
            properties,
            {"name": "First", "email": "first@example.com", "location": "SF"},
        )


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
            fake.assert_called("get_persons_by_distinct_ids_in_team")
            fake.assert_called("get_distinct_ids_for_persons")

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
            fake.assert_called("get_persons_by_distinct_ids_in_team")

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


class TestGetPersonAndDistinctIdsForIdentifierIntegration(BaseTest):
    def test_lookup_by_distinct_id(self):
        person = create_person(
            team=self.team,
            distinct_ids=["d1", "d2"],
            properties={"email": "test@example.com"},
        )

        result_person, result_dids = get_person_and_distinct_ids_for_identifier(self.team.pk, distinct_id="d1")

        assert result_person is not None
        assert str(result_person.uuid) == str(person.uuid)
        assert result_person.properties == {"email": "test@example.com"}
        assert set(result_dids) == {"d1", "d2"}
        get_active_fake().assert_called("get_persons_by_distinct_ids_in_team")

    def test_lookup_by_person_id(self):
        person = create_person(
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
        get_active_fake().assert_called("get_person_by_uuid")

    def test_person_not_found(self):
        result_person, result_dids = get_person_and_distinct_ids_for_identifier(self.team.pk, distinct_id="unknown")

        assert result_person is None
        assert result_dids == []

    def test_cross_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        create_person(team=other_team, distinct_ids=["shared_did"])

        result_person, result_dids = get_person_and_distinct_ids_for_identifier(self.team.pk, distinct_id="shared_did")

        assert result_person is None
        assert result_dids == []
