from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership
from posthog.models.event.new_events_schema import (
    EVENTS_TABLE_ROLLOUT_FLAG,
    EVENTS_TABLE_SELF_SERVE_FLAG,
    clear_project_events_table_choices,
    set_project_events_table_choice,
    use_new_events_schema,
)
from posthog.models.instance_setting import override_instance_config


@override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
class TestEventsTableAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        clear_project_events_table_choices()
        self.addCleanup(clear_project_events_table_choices)
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

    @parameterized.expand(
        [
            ("own_choice_moves_a_project_nobody_moved", True, False, False, True),
            ("own_choice_keeps_a_moved_project_on_the_old_table", False, True, True, False),
            ("no_choice_follows_the_rollout", None, False, True, True),
            ("no_choice_follows_the_staff_list", None, True, False, True),
            ("no_choice_and_not_moved_reads_the_old_table", None, False, False, False),
        ]
    )
    def test_the_projects_choice_wins_over_the_staff_list_and_the_rollout(
        self, _name: str, choice: bool | None, on_staff_list: bool, in_rollout: bool, reads_new_table: bool
    ) -> None:
        self.flags[EVENTS_TABLE_ROLLOUT_FLAG] = in_rollout
        staff_list = str(self.team.pk) if on_staff_list else ""

        with override_instance_config("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS", staff_list):
            response = self.client.post(self.url, {"use_new_events_table": choice}, format="json")

            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
            self.assertEqual(
                response.json(),
                {"use_new_events_table": choice, "reads_new_events_table": reads_new_table, "can_choose": True},
            )
            self.assertEqual(self.client.get(self.url).json(), response.json())
            self.assertEqual(use_new_events_schema(self.team.pk), reads_new_table)

    def test_a_project_that_cannot_choose_is_refused_and_its_stored_choice_is_ignored(self) -> None:
        set_project_events_table_choice(self.team, True)
        self.flags[EVENTS_TABLE_SELF_SERVE_FLAG] = False

        response = self.client.post(self.url, {"use_new_events_table": False}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.get(self.url).json(),
            {"use_new_events_table": None, "reads_new_events_table": False, "can_choose": False},
        )
        self.assertFalse(use_new_events_schema(self.team.pk))

    def test_a_member_who_is_not_an_admin_cannot_switch_the_table(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, {"use_new_events_table": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(use_new_events_schema(self.team.pk))
