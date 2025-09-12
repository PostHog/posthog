import json

import pytest
from posthog.test.base import TestMigrations

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class FixingDashboardTilesTestCase(TestMigrations):
    migrate_from = "0227_add_dashboard_tiles"
    migrate_to = "0228_fix_tile_layouts"

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        Dashboard = apps.get_model("posthog", "Dashboard")
        Insight = apps.get_model("posthog", "Insight")
        Team = apps.get_model("posthog", "Team")
        DashboardTile = apps.get_model("posthog", "DashboardTile")

        org = Organization.objects.create(name="o1")
        team = Team.objects.create(name="t1", organization=org)

        dashboard = Dashboard.objects.create(name="d1", team=team)
        # CASE 1:
        # dashboard tile with valid layouts
        # Expect: no conversion for this tile
        insight_for_case_1 = Insight.objects.create(
            team=team,
            filters={"insight": "TRENDS", "date_from": "-7d"},
            name="has valid layouts on tile",
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight_for_case_1, layouts={"a": "dict"})

        # CASE 2:
        # dashboard with layout that has been stringified once
        # Expect: conversion for this tile
        insight_for_case_2 = Insight.objects.create(
            team=team,
            filters={"insight": "TRENDS", "date_from": "-7d"},
            name="has invalid layouts on tile",
        )
        DashboardTile.objects.create(
            dashboard=dashboard,
            insight=insight_for_case_2,
            layouts=json.dumps({"a": "dict"}),
        )

    def test_migrate_to_create_tiles(self):
        """
        Migration 0227 loaded layouts via SQL query from insights and then saved them to dashboard tiles
        That assumed that when loaded they were dicts.
        However, when a Django model saves a JSONField it runs `jsons.dumps(field)` so it is saving a string
        0227 loaded that string, passed it into a model, and saved it
        So it had effectively had `json.dumps(json.dumps(field)` run on it

        In the meantime if anyone has edited a dashboard the layout will have been saved correctly
        (as a singly string stringified dict)

        A migration to fix that needs to cope with both singly and doubly stringified dicts)
        """
        DashboardTile = self.apps.get_model("posthog", "DashboardTile")  # type: ignore

        # CASE 1:
        self.assertIsInstance(
            DashboardTile.objects.get(dashboard__name="d1", insight__name="has valid layouts on tile").layouts,
            dict,
        )

        # CASE 2:
        self.assertIsInstance(
            DashboardTile.objects.get(dashboard__name="d1", insight__name="has invalid layouts on tile").layouts,
            dict,
        )

    def tearDown(self):
        Team = self.apps.get_model("posthog", "Team")  # type: ignore
        Dashboard = self.apps.get_model("posthog", "Dashboard")  # type: ignore
        Insight = self.apps.get_model("posthog", "Dashboard")  # type: ignore

        Insight.objects.all().delete()
        Dashboard.objects.all().delete()
        Team.objects.all().delete()
