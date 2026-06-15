from typing import Any

import pytest
from posthog.test.base import NonAtomicTestMigrations

from parameterized import parameterized

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class RemovePresortedEventsModifierMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0998_team_proactive_tasks_enabled"
    migrate_to = "0999_remove_presorted_events_modifier"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        Insight = apps.get_model("posthog", "Insight")

        self.organization = Organization.objects.create(name="Test Organization")
        self.project = Project.objects.create(organization=self.organization, name="Test Project", id=1000001)
        self.team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            name="Test Team",
        )
        self.Insight = Insight

        self.insights = {}

        # query.modifiers only
        self.insights["query_modifiers_only"] = Insight.objects.create(
            team=self.team,
            name="Query modifiers only",
            query={"kind": "TrendsQuery", "modifiers": {"usePresortedEventsTable": True}},
        )

        # query.source.modifiers only
        self.insights["source_modifiers_only"] = Insight.objects.create(
            team=self.team,
            name="Source modifiers only",
            query={
                "kind": "DataVisualizationNode",
                "source": {"kind": "TrendsQuery", "modifiers": {"usePresortedEventsTable": False}},
            },
        )

        # Both locations
        self.insights["both_locations"] = Insight.objects.create(
            team=self.team,
            name="Both locations",
            query={
                "kind": "DataVisualizationNode",
                "modifiers": {"usePresortedEventsTable": True},
                "source": {"kind": "TrendsQuery", "modifiers": {"usePresortedEventsTable": False}},
            },
        )

        # Other modifiers preserved
        self.insights["other_modifiers_preserved"] = Insight.objects.create(
            team=self.team,
            name="Other modifiers preserved",
            query={
                "kind": "TrendsQuery",
                "modifiers": {"usePresortedEventsTable": True, "inCohortVia": "subquery"},
            },
        )

        # No usePresortedEventsTable modifier (control case)
        self.insights["no_modifier"] = Insight.objects.create(
            team=self.team,
            name="No modifier",
            query={"kind": "TrendsQuery", "modifiers": {"inCohortVia": "subquery"}},
        )

        # Empty modifiers
        self.insights["empty_modifiers"] = Insight.objects.create(
            team=self.team,
            name="Empty modifiers",
            query={"kind": "TrendsQuery", "modifiers": {}},
        )

        # No modifiers key at all
        self.insights["no_modifiers_key"] = Insight.objects.create(
            team=self.team,
            name="No modifiers key",
            query={"kind": "TrendsQuery"},
        )

        # Other query fields preserved
        self.insights["other_query_fields_preserved"] = Insight.objects.create(
            team=self.team,
            name="Other query fields preserved",
            query={
                "kind": "TrendsQuery",
                "series": [{"event": "pageview", "kind": "EventsNode"}],
                "dateRange": {"date_from": "-7d"},
                "modifiers": {"usePresortedEventsTable": True},
            },
        )

        # Other source fields preserved
        self.insights["other_source_fields_preserved"] = Insight.objects.create(
            team=self.team,
            name="Other source fields preserved",
            query={
                "kind": "DataVisualizationNode",
                "display": "LineChart",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"event": "pageview", "kind": "EventsNode"}],
                    "modifiers": {"usePresortedEventsTable": True},
                },
            },
        )

    @parameterized.expand(
        [
            (
                "query_modifiers_only",
                {"kind": "TrendsQuery", "modifiers": {}},
            ),
            (
                "source_modifiers_only",
                {"kind": "DataVisualizationNode", "source": {"kind": "TrendsQuery", "modifiers": {}}},
            ),
            (
                "both_locations",
                {
                    "kind": "DataVisualizationNode",
                    "modifiers": {},
                    "source": {"kind": "TrendsQuery", "modifiers": {}},
                },
            ),
            (
                "other_modifiers_preserved",
                {"kind": "TrendsQuery", "modifiers": {"inCohortVia": "subquery"}},
            ),
            (
                "no_modifier",
                {"kind": "TrendsQuery", "modifiers": {"inCohortVia": "subquery"}},
            ),
            (
                "empty_modifiers",
                {"kind": "TrendsQuery", "modifiers": {}},
            ),
            (
                "no_modifiers_key",
                {"kind": "TrendsQuery"},
            ),
            (
                "other_query_fields_preserved",
                {
                    "kind": "TrendsQuery",
                    "series": [{"event": "pageview", "kind": "EventsNode"}],
                    "dateRange": {"date_from": "-7d"},
                    "modifiers": {},
                },
            ),
            (
                "other_source_fields_preserved",
                {
                    "kind": "DataVisualizationNode",
                    "display": "LineChart",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [{"event": "pageview", "kind": "EventsNode"}],
                        "modifiers": {},
                    },
                },
            ),
        ]
    )
    def test_presorted_events_modifier_removed(self, insight_key, expected_query):
        insight = self.insights[insight_key]
        insight.refresh_from_db()

        self.assertEqual(insight.query, expected_query)
