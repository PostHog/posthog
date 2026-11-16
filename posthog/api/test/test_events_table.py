from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership
from posthog.models.event.new_events_schema import (
    EVENTS_TABLE_ROLLOUT_FLAG,
    EVENTS_TABLE_SELF_SERVE_FLAG,
    clear_events_table_opt_ins,
    set_project_events_table_opt_in,
    use_new_events_schema,
)
from posthog.models.instance_setting import override_instance_config


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestEventsTableAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        clear_events_table_opt_ins()
        self.addCleanup(clear_events_table_opt_ins)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.flags: dict[str, bool] = {EVENTS_TABLE_SELF_SERVE_FLAG: True}
        self.enterContext(patch("posthog.models.event.new_events_schema.is_cloud", return_value=True))
        self.enterContext(
            patch(
                "posthog.models.event.new_events_schema.posthoganalytics.feature_enabled",
                side_effect=lambda flag, *args, **kwargs: self.flags.get(flag, False),
            )
        )
        self.url = f"/api/projects/{self.team.pk}/events_table/"

    def test_a_project_moves_early_by_opting_in_and_back_by_opting_out(self) -> None:
        response = self.client.post(self.url, {"use_new_events_table": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(
            response.json(), {"use_new_events_table": True, "reads_new_events_table": True, "can_choose": True}
        )
        self.assertTrue(use_new_events_schema(self.team.pk))

        response = self.client.post(self.url, {"use_new_events_table": False}, format="json")

        self.assertEqual(
            response.json(), {"use_new_events_table": False, "reads_new_events_table": False, "can_choose": True}
        )
        self.assertFalse(use_new_events_schema(self.team.pk))

    @parameterized.expand(
        [
            ("moved_by_the_staff_list", True, False, False),
            ("moved_by_the_rollout", False, True, False),
            ("moved_by_the_rollout_after_opting_in", False, True, True),
        ]
    )
    def test_a_project_that_posthog_moved_cannot_switch_back(
        self, _name: str, on_staff_list: bool, in_rollout: bool, opted_in_before: bool
    ) -> None:
        set_project_events_table_opt_in(self.team, opted_in_before)
        self.flags[EVENTS_TABLE_ROLLOUT_FLAG] = in_rollout
        staff_list = str(self.team.pk) if on_staff_list else ""

        with override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", staff_list):
            response = self.client.post(self.url, {"use_new_events_table": False}, format="json")

            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(
                self.client.get(self.url).json(),
                {"use_new_events_table": opted_in_before, "reads_new_events_table": True, "can_choose": False},
            )
            self.assertTrue(use_new_events_schema(self.team.pk))

    def test_a_project_that_cannot_opt_in_is_refused_and_its_stored_opt_in_is_ignored(self) -> None:
        set_project_events_table_opt_in(self.team, True)
        self.flags[EVENTS_TABLE_SELF_SERVE_FLAG] = False

        response = self.client.post(self.url, {"use_new_events_table": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.get(self.url).json(),
            {"use_new_events_table": False, "reads_new_events_table": False, "can_choose": False},
        )
        self.assertFalse(use_new_events_schema(self.team.pk))

    def test_a_member_who_is_not_an_admin_cannot_switch_the_table(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, {"use_new_events_table": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(use_new_events_schema(self.team.pk))
