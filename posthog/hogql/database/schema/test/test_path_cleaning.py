import uuid
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin
from posthog.models.utils import uuid7
from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.test.test_utils import _create_event


class TestPathCleaningVirtualField(ClickhouseTestMixin):
    def setUp(self):
        super().setUp()
        # Set up default path cleaning filters
        self.team.path_cleaning_filters = [
            {
                "regex": r"/product/\d+",
                "alias": "/product/*"
            },
            {
                "regex": r"/users/[^/]+/profile", 
                "alias": "/users/*/profile"
            }
        ]
        self.team.save()

    def _get_event_path_cleaned_pathname(self, pathname: str):
        """Helper to create event and query the virtual field"""
        person_id = str(uuid.uuid4())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=person_id,
            properties={
                "$session_id": str(uuid7()),
                "$pathname": pathname,
            },
        )

        # Flush events to ensure they're available for querying
        from posthog.test.base import flush_persons_and_events
        flush_persons_and_events()

        # Let's try a simpler approach and just check all available fields on the event
        response = execute_hogql_query(
            parse_select(
                """
                select
                    properties.$pathname as original_pathname,
                    $virt_path_cleaned_pathname as cleaned_pathname
                from events
                where distinct_id = {person_id}
                """,
                placeholders={"person_id": ast.Constant(value=person_id)},
            ),
            self.team,
        )

        if response.results and len(response.results[0]) >= 2:
            return response.results[0][1]  # Return the cleaned pathname
        return None

    def test_no_path_cleaning_rules(self):
        """Test that when there are no path cleaning rules, original pathname is returned"""
        # Clear path cleaning filters
        self.team.path_cleaning_filters = []
        self.team.save()

        original_path = "/product/123/details"
        cleaned_path = self._get_event_path_cleaned_pathname(original_path)

        self.assertEqual(cleaned_path, original_path)

    def test_single_rule_match(self):
        """Test path cleaning with a single matching rule"""
        original_path = "/product/123"
        cleaned_path = self._get_event_path_cleaned_pathname(original_path)

        self.assertEqual(cleaned_path, "/product/*")

    def test_no_rule_match(self):
        """Test path that doesn't match any cleaning rules"""
        original_path = "/about/us"
        cleaned_path = self._get_event_path_cleaned_pathname(original_path)

        self.assertEqual(cleaned_path, "/about/us")

    def test_multiple_rules_applied_sequentially(self):
        """Test that all matching rules are applied sequentially"""
        # Add overlapping rules - both will be applied in order
        self.team.path_cleaning_filters = [
            {
                "regex": r"/product/\d+",
                "alias": "/product/*"
            },
            {
                "regex": r"/product/\d+/.*",
                "alias": "/product/*/details"
            }
        ]
        self.team.save()

        original_path = "/product/123/details"
        cleaned_path = self._get_event_path_cleaned_pathname(original_path)

        # All rules are applied sequentially:
        # 1. /product/123/details -> /product/*/details (first rule)
        # 2. /product/*/details -> /product/*/details (second rule matches and replaces)
        self.assertEqual(cleaned_path, "/product/*/details")

    def test_complex_regex_patterns(self):
        """Test more complex regex patterns"""
        self.team.path_cleaning_filters = [
            {
                "regex": r"/api/v\d+/users/[^/]+",
                "alias": "/api/v*/users/*"
            },
            {
                "regex": r"/dashboard/[0-9a-f-]{36}/.*",
                "alias": "/dashboard/*/..."
            }
        ]
        self.team.save()

        # Test API pattern
        api_path = "/api/v2/users/john_doe"
        cleaned_api = self._get_event_path_cleaned_pathname(api_path)
        self.assertEqual(cleaned_api, "/api/v*/users/*")

        # Test UUID pattern
        uuid_path = f"/dashboard/{str(uuid.uuid4())}/settings/billing"
        cleaned_uuid = self._get_event_path_cleaned_pathname(uuid_path)
        self.assertEqual(cleaned_uuid, "/dashboard/*/...")

    def test_user_profile_pattern(self):
        """Test the user profile pattern from setUp"""
        original_path = "/users/johndoe/profile"
        cleaned_path = self._get_event_path_cleaned_pathname(original_path)

        self.assertEqual(cleaned_path, "/users/*/profile")

    def test_empty_pathname(self):
        """Test behavior with empty pathname"""
        original_path = ""
        cleaned_path = self._get_event_path_cleaned_pathname(original_path)

        self.assertEqual(cleaned_path, "")

    def test_null_pathname(self):
        """Test behavior when pathname is None"""
        person_id = str(uuid.uuid4())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=person_id,
            properties={
                "$session_id": str(uuid7()),
                # No $pathname property
            },
        )

        response = execute_hogql_query(
            parse_select(
                "select $virt_path_cleaned_pathname as cleaned_pathname from events where distinct_id = {person_id}",
                placeholders={"person_id": ast.Constant(value=person_id)},
            ),
            self.team,
        )

        # Should be None/null when no pathname is present
        self.assertIsNone(response.results[0][0])

    def test_special_characters_in_path(self):
        """Test paths with special characters"""
        self.team.path_cleaning_filters = [
            {
                "regex": r"/search\?.*",
                "alias": "/search"
            }
        ]
        self.team.save()

        original_path = "/search?query=test&category=books"
        cleaned_path = self._get_event_path_cleaned_pathname(original_path)

        self.assertEqual(cleaned_path, "/search")

    def test_can_query_in_sql_editor_context(self):
        """Test that the virtual field works in SQL Editor context with multiple events"""
        # Create multiple events with different pathnames
        paths = ["/product/123", "/product/456", "/about", "/users/alice/profile"]
        person_ids = []

        for path in paths:
            person_id = str(uuid.uuid4())
            person_ids.append(person_id)
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id=person_id,
                properties={
                    "$session_id": str(uuid7()),
                    "$pathname": path,
                },
            )

        # Query all events with the virtual field
        response = execute_hogql_query(
            parse_select(
                """
                select
                    properties.$pathname as original_path,
                    $virt_path_cleaned_pathname as cleaned_path
                from events
                where distinct_id in {person_ids}
                order by properties.$pathname
                """,
                placeholders={"person_ids": ast.Constant(value=person_ids)},
            ),
            self.team,
        )

        expected_results = [
            ("/about", "/about"),  # No cleaning rule
            ("/product/123", "/product/*"),  # Cleaned
            ("/product/456", "/product/*"),  # Cleaned
            ("/users/alice/profile", "/users/*/profile"),  # Cleaned
        ]

        self.assertEqual(len(response.results), 4)
        self.assertEqual(response.results, expected_results)