from typing import Any

import pytest
from posthog.test.base import NonAtomicTestMigrations

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class ConvertPersonsNodeInsightsToActorsQueryMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0458_alter_insightviewed_team_alter_insightviewed_user"
    migrate_to = "0459_convert_personsnode_insights_to_actorsquery"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        Insight = apps.get_model("posthog", "Insight")

        self.organization = Organization.objects.create(name="o1")
        self.project = Project.objects.create(organization=self.organization, name="p1", id=1000001)
        self.team = Team.objects.create(organization=self.organization, name="t1", project=self.project)

        self.insight_1 = Insight.objects.create(
            team=self.team,
            query={"full": True, "kind": "DataTableNode", "source": {"kind": "PersonsNode", "cohort": "4669"}},
        )
        self.insight_2 = Insight.objects.create(
            team=self.team,
            deleted=True,
            query={
                "full": True,
                "kind": "DataTableNode",
                "source": {"kind": "PersonsNode", "search": "@"},
                "propertiesViaUrl": True,
            },
        )
        self.insight_3 = Insight.objects.create(
            team=self.team,
            query={
                "full": True,
                "kind": "DataTableNode",
                "source": {
                    "kind": "PersonsNode",
                    "properties": [{"key": "email", "type": "person", "value": "is_set", "operator": "is_set"}],
                },
                "propertiesViaUrl": True,
            },
        )
        self.insight_4 = Insight.objects.create(
            team=self.team,
            query={
                "full": True,
                "kind": "DataTableNode",
                "source": {
                    "kind": "PersonsNode",
                    "cohort": "3",
                    "properties": [{"key": "email", "type": "person", "value": "is_set", "operator": "is_set"}],
                },
                "propertiesViaUrl": True,
            },
        )
        self.insight_5 = Insight.objects.create(
            team=self.team,
            query={"full": True, "kind": "DataTableNode", "source": {"kind": "PersonsNode"}, "propertiesViaUrl": True},
        )
        self.insight_6 = Insight.objects.create(
            team=self.team,
            query={
                "full": True,
                "kind": "DataTableNode",
                "source": {
                    "kind": "PersonsNode",
                    "fixedProperties": [{"key": "email", "type": "person", "value": "is_set", "operator": "is_set"}],
                    "properties": [
                        {"key": "name", "type": "person", "value": "is_set", "operator": "is_set"},
                        {"key": "surname", "type": "person", "value": "is_set", "operator": "is_set"},
                        {"key": "id", "type": "cohort", "value": 3},
                    ],
                    "limit": 100,
                    "offset": 100,
                },
                "propertiesViaUrl": True,
            },
        )
        self.insight_7 = Insight.objects.create(
            team=self.team,
            query={
                "kind": "DataTableNode",
                "source": {
                    "kind": "ActorsQuery",
                    "cohort": 3,
                },
            },
        )
        self.insight_8 = Insight.objects.create(
            team=self.team,
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "cohort": 3,
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
        )

    def test_migration(self) -> None:
        # Ensure self.apps is not None
        assert self.apps is not None

        self.insight_1.refresh_from_db()
        self.assertEqual(
            self.insight_1.query,
            {
                "full": True,
                "kind": "DataTableNode",
                "source": {
                    "kind": "ActorsQuery",
                    "properties": [{"key": "id", "type": "cohort", "operator": "in", "value": 4669}],
                },
            },
        )

        self.insight_2.refresh_from_db()
        self.assertEqual(
            self.insight_2.query,
            {
                "full": True,
                "kind": "DataTableNode",
                "source": {"kind": "ActorsQuery", "search": "@", "properties": []},
                "propertiesViaUrl": True,
            },
        )

        self.insight_3.refresh_from_db()
        self.assertEqual(
            self.insight_3.query,
            {
                "full": True,
                "kind": "DataTableNode",
                "source": {
                    "kind": "ActorsQuery",
                    "properties": [{"key": "email", "type": "person", "value": "is_set", "operator": "is_set"}],
                },
                "propertiesViaUrl": True,
            },
        )

        self.insight_4.refresh_from_db()
        self.assertEqual(
            self.insight_4.query,
            {
                "full": True,
                "kind": "DataTableNode",
                "source": {
                    "kind": "ActorsQuery",
                    "properties": [
                        {"key": "email", "type": "person", "value": "is_set", "operator": "is_set"},
                        {"key": "id", "type": "cohort", "operator": "in", "value": 3},
                    ],
                },
                "propertiesViaUrl": True,
            },
        )

        self.insight_5.refresh_from_db()
        self.assertEqual(
            self.insight_5.query,
            {
                "full": True,
                "kind": "DataTableNode",
                "source": {"kind": "ActorsQuery", "properties": []},
                "propertiesViaUrl": True,
            },
        )

        self.insight_6.refresh_from_db()
        self.assertEqual(
            self.insight_6.query,
            {
                "full": True,
                "kind": "DataTableNode",
                "source": {
                    "kind": "ActorsQuery",
                    "fixedProperties": [{"key": "email", "type": "person", "value": "is_set", "operator": "is_set"}],
                    "properties": [
                        {"key": "name", "type": "person", "value": "is_set", "operator": "is_set"},
                        {"key": "surname", "type": "person", "value": "is_set", "operator": "is_set"},
                        {"key": "id", "type": "cohort", "operator": "in", "value": 3},
                    ],
                    "limit": 100,
                    "offset": 100,
                },
                "propertiesViaUrl": True,
            },
        )

        self.insight_7.refresh_from_db()
        self.assertEqual(
            self.insight_7.query,
            {
                "kind": "DataTableNode",
                "source": {
                    "kind": "ActorsQuery",
                    "cohort": 3,
                },
            },
        )

        self.insight_8.refresh_from_db()
        self.assertEqual(
            self.insight_8.query,
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "cohort": 3,
                },
            },
        )

    def tearDown(self) -> None:
        # Ensure self.apps is not None
        assert self.apps is not None

        Insight = self.apps.get_model("posthog", "Insight")
        Insight.objects.all().delete()
        self.team.delete()
        self.project.delete()
        self.organization.delete()

        super().tearDown()
