from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import ActivityLog, OrganizationMembership, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration, PlatformAlertThread

CONDITION = {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}


class TestPlatformAlertAPI(APIBaseTest):
    def _create_configuration(
        self,
        team: Team,
        name: str,
        legacy_configuration_id: UUID | None = None,
        source_kind: str = PlatformAlertConfiguration.SourceKind.LOGS,
        owner: str = PlatformAlertConfiguration.Owner.SOURCE,
    ) -> PlatformAlertConfiguration:
        with team_scope(team.id):
            return PlatformAlertConfiguration.objects.create(
                team=team,
                name=name,
                source_kind=source_kind,
                source_config={"filters": {"serviceNames": ["api"]}, "condition": CONDITION},
                check_interval_minutes=10,
                legacy_configuration_id=legacy_configuration_id,
                owner=owner,
            )

    def _set_flag(self, enabled: bool) -> None:
        self.enterContext(patch("posthog.permissions.posthog_feature_flag_enabled", return_value=enabled))

    @parameterized.expand([("list", False), ("retrieve", True)])
    def test_flag_off_blocks_access(self, _name: str, with_id: bool) -> None:
        self._set_flag(False)
        configuration = self._create_configuration(self.team, "API errors")
        url = f"/api/projects/{self.team.id}/platform_alerts/"
        if with_id:
            url += f"{configuration.id}/"

        response = self.client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "feature_flag_required"

    def test_list_returns_own_configurations_with_nested_alerts(self) -> None:
        self._set_flag(True)
        legacy_configuration_id = uuid4()
        configuration = self._create_configuration(self.team, "API errors", legacy_configuration_id)
        firing_started_at = datetime(2026, 9, 16, 10, tzinfo=UTC)
        with team_scope(self.team.id):
            alert = PlatformAlert.objects.create(
                team=self.team,
                configuration=configuration,
                grouping_key="checkout",
                state=PlatformAlert.State.FIRING,
                firing_started_at=firing_started_at,
                last_notified_at=firing_started_at,
                labels={"service_name": "checkout"},
            )
            PlatformAlertConfiguration.objects.filter(id=configuration.id).update(
                overflowed_groups=2, overflow_is_lower_bound=True
            )
        list_response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/")

        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        results = list_response.json()["results"]
        assert [r["id"] for r in results] == [str(configuration.id)]
        assert results[0]["legacy_configuration_id"] == str(legacy_configuration_id)
        assert (results[0]["overflowed_groups"], results[0]["overflow_is_lower_bound"]) == (2, True)
        assert results[0]["alerts"] == [
            {
                "id": str(alert.id),
                "grouping_key": "checkout",
                "state": "firing",
                "firing_started_at": "2026-09-16T10:00:00Z",
                "last_notified_at": "2026-09-16T10:00:00Z",
                "snooze_until": None,
                "labels": {"service_name": "checkout"},
            }
        ]

    def test_a_child_environment_reads_its_parents_configurations(self) -> None:
        # The viewset resolves a child environment to its parent before reading, so a request
        # against the child sees the parent's rows rather than an empty project.
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors")
        child_environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")

        response = self.client.get(f"/api/projects/{child_environment.id}/platform_alerts/{configuration.id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == str(configuration.id)

    @parameterized.expand(
        [
            ("key_for_the_environment_only", False, status.HTTP_403_FORBIDDEN),
            ("key_for_the_environment_and_its_project", True, status.HTTP_200_OK),
        ]
    )
    def test_a_project_scoped_key_reaches_a_child_environments_alerts_only_with_the_parent(
        self, _name: str, scoped_to_parent: bool, expected: int
    ) -> None:
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors", owner="platform")
        child_environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Environment key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["alert:read", "alert:write", "logs:read", "logs:write"],
            scoped_teams=[child_environment.id, self.team.id] if scoped_to_parent else [child_environment.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key_value}")
        url = f"/api/projects/{child_environment.id}/platform_alerts/{configuration.id}/"

        edit = self.client.patch(url, {"name": "Renamed"}, format="json")
        read = self.client.get(url)

        assert (edit.status_code, read.status_code) == (expected, expected), (edit.json(), read.json())
        configuration.refresh_from_db()
        assert configuration.name == ("Renamed" if expected == status.HTTP_200_OK else "API errors")

    def test_another_teams_configuration_is_not_found(self) -> None:
        self._set_flag(True)
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_configuration = self._create_configuration(other_team, "Other team errors")

        response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/{other_configuration.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("logs_member_without_access", "logs", None, False),
            ("logs_key_without_scope", "logs", ["alert:read"], False),
            ("logs_key_with_scope", "logs", ["alert:read", "logs:read"], True),
            ("insight_key_with_scope", "insight", ["alert:read", "insight:read"], False),
        ]
    )
    def test_a_configuration_needs_read_access_to_its_source_product(
        self, _name: str, source_kind: str, key_scopes: list[str] | None, visible: bool
    ) -> None:
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors", source_kind=source_kind)
        if key_scopes is None:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            member = User.objects.create_and_join(self.organization, "alerts-only@posthog.com", "testtest")
            AccessControl.objects.create(
                team=self.team,
                resource=source_kind,
                resource_id=None,
                access_level="none",
                organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
            )
            self.client.force_login(member)
        else:
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(key_scopes)}")

        list_response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/")
        retrieve_response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/{configuration.id}/")

        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        assert [r["id"] for r in list_response.json()["results"]] == ([str(configuration.id)] if visible else [])
        expected_retrieve_status = status.HTTP_200_OK if visible else status.HTTP_404_NOT_FOUND
        assert retrieve_response.status_code == expected_retrieve_status, retrieve_response.json()

    def test_a_logs_denial_on_the_parent_survives_a_child_environment_url(self) -> None:
        # The rows are read from the parent, so the access check has to be read from the parent
        # too. Anchored on the URL's team instead, a deny written on the project is invisible to a
        # request that names one of its environments, and the parent's `source_config` filters are
        # exactly what the deny was protecting.
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors")
        child_environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "denied-logs@posthog.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="logs",
            resource_id=None,
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
        )
        self.client.force_login(member)

        list_response = self.client.get(f"/api/projects/{child_environment.id}/platform_alerts/")
        retrieve_response = self.client.get(f"/api/projects/{child_environment.id}/platform_alerts/{configuration.id}/")

        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        assert [r["id"] for r in list_response.json()["results"]] == []
        assert retrieve_response.status_code == status.HTTP_404_NOT_FOUND, retrieve_response.json()

    @parameterized.expand([("retrieve", "not-a-uuid/"), ("legacy_id_filter", "?legacy_configuration_id=not-a-uuid")])
    def test_a_malformed_id_is_refused_rather_than_raising(self, _name: str, path: str) -> None:
        self._set_flag(True)

        response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/{path}")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_two_pages_cover_every_row_once(self) -> None:
        # `list` asks the facade for a slice and then hands that slice to the paginator. An offset
        # applied by both would skip rows at the page boundary, which a single-page test cannot see.
        self._set_flag(True)
        created = {str(self._create_configuration(self.team, f"Alert {index}").id) for index in range(3)}
        url = f"/api/projects/{self.team.id}/platform_alerts/"

        first = self.client.get(f"{url}?limit=2").json()
        second = self.client.get(f"{url}?limit=2&offset=2").json()

        first_ids = [row["id"] for row in first["results"]]
        second_ids = [row["id"] for row in second["results"]]
        assert first["count"] == 3
        assert len(first_ids) == 2
        assert len(second_ids) == 1
        assert set(first_ids).isdisjoint(second_ids)
        assert set(first_ids) | set(second_ids) == created

    def test_the_legacy_id_filter_finds_the_copy_of_one_source_alert(self) -> None:
        self._set_flag(True)
        legacy_configuration_id = uuid4()
        wanted = self._create_configuration(self.team, "Copied", legacy_configuration_id=legacy_configuration_id)
        self._create_configuration(self.team, "Another copy", legacy_configuration_id=uuid4())

        response = self.client.get(
            f"/api/projects/{self.team.id}/platform_alerts/?legacy_configuration_id={legacy_configuration_id}"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [(row["id"], response.json()["count"]) for row in response.json()["results"]] == [(str(wanted.id), 1)]

    def test_a_page_costs_the_same_queries_however_many_rows_it_holds(self) -> None:
        # A filter added to the prefetched relation would bypass the cache and cost a query per
        # configuration, which no assertion on the response body would notice.
        self._set_flag(True)
        for index in range(4):
            self._create_configuration(self.team, f"Alert {index}")
        url = f"/api/projects/{self.team.id}/platform_alerts/"

        self.client.get(f"{url}?limit=1")  # The first request of a test warms caches the rest reuse.

        assert self._queries_for(f"{url}?limit=4") == self._queries_for(f"{url}?limit=1")

    def _queries_for(self, url: str) -> int:
        with CaptureQueriesContext(connection) as captured:
            self.client.get(url)
        return len(captured)

    def _edit_url(self, configuration: PlatformAlertConfiguration) -> str:
        return f"/api/projects/{self.team.id}/platform_alerts/{configuration.id}/"

    def test_changing_the_grouping_keys_drops_the_old_instances_and_their_threads(self) -> None:
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors", owner="platform")
        with team_scope(self.team.id):
            PlatformAlert.objects.create(team=self.team, configuration=configuration, state=PlatformAlert.State.FIRING)
            PlatformAlertConfiguration.objects.filter(id=configuration.id).update(
                overflowed_groups=4, overflow_is_lower_bound=True
            )
            PlatformAlertThread.objects.create(
                team=self.team,
                configuration=configuration,
                provider="slack",
                channel_target="C1",
                episode_started_at=datetime(2026, 10, 1, tzinfo=UTC),
            )

        response = self.client.patch(
            self._edit_url(configuration),
            {"grouping": {"mode": "by_result_labels", "keys": ["service_name"]}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["grouping"] == {
            "mode": "by_result_labels",
            "keys": ["service_name"],
            "max_instances": 100,
            "on_overflow": "degrade_visible",
        }
        assert (body["name"], body["alerts"]) == ("API errors", [])
        assert (body["overflowed_groups"], body["overflow_is_lower_bound"]) == (0, False)
        with team_scope(self.team.id):
            assert not PlatformAlertThread.objects.filter(configuration=configuration).exists()

    @parameterized.expand([("edit",), ("delete",)])
    def test_an_alert_its_source_owns_is_not_written_here(self, write: str) -> None:
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors")

        if write == "edit":
            response = self.client.patch(
                self._edit_url(configuration), {"name": "Renamed", "evaluation_periods": 0}, format="json"
            )
        else:
            response = self.client.delete(self._edit_url(configuration))

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        configuration.refresh_from_db()
        assert configuration.name == "API errors"

    @parameterized.expand(
        [
            (
                "grouped_below",
                {
                    "grouping": {"mode": "by_result_labels", "keys": ["service_name"]},
                    "source_config": {
                        "filters": {"serviceNames": ["api"]},
                        "condition": {**CONDITION, "threshold_operator": "below"},
                    },
                },
                "grouping",
            ),
            (
                "unknown_window",
                {
                    "source_config": {
                        "filters": {"serviceNames": ["api"]},
                        "condition": {**CONDITION, "window_minutes": 7},
                    }
                },
                "source_config",
            ),
            (
                "more_datapoints_than_periods",
                {"evaluation_periods": 2, "datapoints_to_alarm": 3},
                "datapoints_to_alarm",
            ),
            ("source_kind_changed", {"source_kind": "insight"}, "source_kind"),
            ("cooldown_past_the_column", {"cooldown_minutes": 2_147_483_648}, "cooldown_minutes"),
            ("grouping_without_mode", {"grouping": {"keys": ["service_name"]}}, "grouping__mode"),
            ("enabled_without_filters", {"source_config": {"filters": {}, "condition": CONDITION}}, "source_config"),
            ("grouped_by_an_attribute", {"grouping": {"mode": "by_result_labels", "keys": ["http.route"]}}, "grouping"),
        ]
    )
    def test_an_invalid_edit_names_the_field_and_changes_nothing(self, _name: str, body: dict, field: str) -> None:
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors", owner="platform")

        response = self.client.patch(self._edit_url(configuration), body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == field
        configuration.refresh_from_db()
        assert (configuration.source_config["condition"], configuration.grouping["mode"]) == (CONDITION, "single")

    @parameterized.expand(
        [
            ("alert_scope_only", ["alert:write"], status.HTTP_404_NOT_FOUND),
            ("logs_read_only", ["alert:write", "logs:read"], status.HTTP_403_FORBIDDEN),
            ("alert_and_logs_write", ["alert:write", "logs:write"], status.HTTP_200_OK),
        ]
    )
    def test_an_edit_needs_write_access_to_the_source_product(
        self, _name: str, key_scopes: list[str], expected: int
    ) -> None:
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors", owner="platform")
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(key_scopes)}")

        response = self.client.patch(self._edit_url(configuration), {"name": "Renamed"}, format="json")

        assert response.status_code == expected, response.json()

    def test_settings_an_edit_leaves_alone_are_not_revalidated(self) -> None:
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors", owner="platform")
        PlatformAlertConfiguration.objects.for_team(self.team.id).filter(id=configuration.id).update(
            source_config={"filters": {"serviceNames": ["api"], "retiredKey": True}, "condition": CONDITION}
        )

        response = self.client.patch(self._edit_url(configuration), {"name": "Renamed"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["name"] == "Renamed"

    def test_turning_a_broken_alert_back_on_schedules_a_clean_check(self) -> None:
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors", owner="platform")
        PlatformAlertConfiguration.objects.for_team(self.team.id).filter(id=configuration.id).update(
            enabled=False, check_status="broken", consecutive_failures=5, next_check_at=None
        )

        response = self.client.patch(self._edit_url(configuration), {"enabled": True}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        with team_scope(self.team.id):
            configuration.refresh_from_db()
        assert (configuration.check_status, configuration.consecutive_failures) == ("ok", 0)
        assert configuration.next_check_at is not None

    def test_an_edit_logs_the_settings_it_changed_and_runtime_writes_log_nothing(self) -> None:
        self._set_flag(True)
        self._create_configuration(self.team, "Seed copy")
        configuration = self._create_configuration(self.team, "API errors", owner="platform")
        with team_scope(self.team.id):
            configuration.next_check_at = datetime(2026, 10, 1, tzinfo=UTC)
            configuration.consecutive_failures = 3
            configuration.save(update_fields=["next_check_at", "consecutive_failures"])

        response = self.client.patch(self._edit_url(configuration), {"name": "Renamed"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        logged = ActivityLog.objects.filter(team_id=self.team.id, scope="PlatformAlertConfiguration")
        assert [(row.item_id, row.activity) for row in logged.order_by("created_at")] == [
            (str(configuration.id), "created"),
            (str(configuration.id), "updated"),
        ]
        edit = logged.get(activity="updated")
        assert edit.user == self.user and edit.detail is not None
        assert [(change["field"], change["before"], change["after"]) for change in edit.detail["changes"]] == [
            ("name", "API errors", "Renamed")
        ]

    def _grouped_configuration(self, owner: str = "platform") -> PlatformAlertConfiguration:
        configuration = self._create_configuration(self.team, "API errors", owner=owner)
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=configuration.id).update(
                grouping={"mode": "by_result_labels", "keys": ["service_name"]}
            )
            for key in ("checkout", "api"):
                PlatformAlert.objects.create(
                    team=self.team, configuration=configuration, grouping_key=key, state=PlatformAlert.State.FIRING
                )
        return configuration

    def _snoozes(self, configuration: PlatformAlertConfiguration) -> dict[str, datetime | None]:
        with team_scope(self.team.id):
            return dict(
                PlatformAlert.objects.filter(configuration=configuration).values_list("grouping_key", "snooze_until")
            )

    def test_snoozing_a_group_mutes_only_that_group_and_clearing_it_unmutes(self) -> None:
        self._set_flag(True)
        configuration = self._grouped_configuration()
        url = f"{self._edit_url(configuration)}snooze_group/"
        until = datetime(2026, 10, 1, 12, tzinfo=UTC)
        # A key rather than a session, because a custom action without a declared scope refuses keys.
        self.client.logout()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(['alert:write', 'logs:write'])}"
        )

        with time_machine.travel(datetime(2026, 10, 1, 10, tzinfo=UTC), tick=False):
            snoozed = self.client.post(url, {"grouping_key": "checkout", "snooze_until": until}, format="json")

        assert snoozed.status_code == status.HTTP_200_OK, snoozed.json()
        assert (snoozed.json()["grouping_key"], snoozed.json()["snooze_until"]) == ("checkout", "2026-10-01T12:00:00Z")
        assert self._snoozes(configuration) == {"checkout": until, "api": None}
        with team_scope(self.team.id):
            assert set(PlatformAlert.objects.filter(configuration=configuration).values_list("state", flat=True)) == {
                "firing"
            }

        cleared = self.client.post(url, {"grouping_key": "checkout", "snooze_until": None}, format="json")

        assert cleared.status_code == status.HTTP_200_OK, cleared.json()
        assert self._snoozes(configuration) == {"checkout": None, "api": None}

    @parameterized.expand(
        [
            ("owned_by_its_source", {"owner": "source"}, {}, status.HTTP_409_CONFLICT, None),
            ("unknown_group", {}, {"grouping_key": "web"}, status.HTTP_404_NOT_FOUND, None),
            (
                "time_in_the_past",
                {},
                {"snooze_until": "2026-10-01T09:00:00Z"},
                status.HTTP_400_BAD_REQUEST,
                "snooze_until",
            ),
            (
                "time_past_the_limit",
                {},
                {"snooze_until": "2026-11-15T12:00:00Z"},
                status.HTTP_400_BAD_REQUEST,
                "snooze_until",
            ),
            ("ungrouped_alert", {"grouped": False}, {}, status.HTTP_400_BAD_REQUEST, "grouping_key"),
        ]
    )
    def test_a_refused_group_snooze_changes_nothing(
        self, _name: str, setup: dict[str, Any], body: dict[str, Any], expected: int, field: str | None
    ) -> None:
        self._set_flag(True)
        configuration = self._grouped_configuration(owner=setup.get("owner", "platform"))
        if setup.get("grouped") is False:
            with team_scope(self.team.id):
                PlatformAlertConfiguration.objects.filter(id=configuration.id).update(grouping={"mode": "single"})
        url = f"{self._edit_url(configuration)}snooze_group/"

        with time_machine.travel(datetime(2026, 10, 1, 10, tzinfo=UTC), tick=False):
            response = self.client.post(
                url, {"grouping_key": "checkout", "snooze_until": "2026-10-01T12:00:00Z", **body}, format="json"
            )

        assert response.status_code == expected, response.json()
        if field is not None:
            assert response.json()["attr"] == field
        assert self._snoozes(configuration) == {"checkout": None, "api": None}
