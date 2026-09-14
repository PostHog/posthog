from __future__ import annotations

from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.conversations.backend.api.ticket_pattern_ai_scan import (
    SCOUT_SKILL_NAME,
    SCOUT_SOURCE_PRODUCT,
    canonical_scout_definition,
)
from products.signals.backend.facade.api import ScoutCreated, ScoutForSource, ScoutReport

FACADE = "products.conversations.backend.api.ticket_pattern_ai_scan.signals_facade"


def _scout(enabled: bool = True, skill_exists: bool = True) -> ScoutForSource:
    return ScoutForSource(
        config_id="019f9582-0000-7000-8000-000000000001",
        skill_name=SCOUT_SKILL_NAME,
        enabled=enabled,
        skill_exists=skill_exists,
        last_run_at=datetime(2026, 7, 25, 10, 0, tzinfo=UTC),
        slack_channel=None,
    )


class TestCanonicalScoutDefinition(APIBaseTest):
    def test_the_shipped_skill_parses_into_a_description_and_a_body(self):
        description, body = canonical_scout_definition()

        assert description.startswith("Hourly AI scan of a Conversations support inbox")
        assert body.startswith("# Signals scout: ticket patterns")
        assert "conversations-patterns-list" in body


class TestTicketPatternAiScanAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/conversations/pattern_ai_scan/"
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"pattern_detection_enabled": True}
        self.team.save()
        flag = patch(
            "products.conversations.backend.api.ticket_pattern_ai_scan.is_pattern_detection_enabled",
            side_effect=lambda team: bool((team.conversations_settings or {}).get("pattern_detection_enabled")),
        )
        flag.start()
        self.addCleanup(flag.stop)

    def test_status_reports_no_scout_and_consent(self):
        with patch(f"{FACADE}.scout_for_source", return_value=None):
            response = self.client.get(f"{self.url}status/")

        assert response.json() == {
            "enabled": False,
            "scout_config_id": None,
            "skill_name": None,
            "last_run_at": None,
            "ai_consent_granted": True,
        }

    def test_enable_creates_the_scout_from_the_canonical_skill_stamped_with_this_team(self):
        with (
            patch(f"{FACADE}.scout_for_source", side_effect=[None, _scout()]),
            patch(f"{FACADE}.create_scout_for_source") as create,
        ):
            create.return_value = ScoutCreated(skill=None, config=None, created=True)
            response = self.client.post(self.url, {}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        kwargs = create.call_args.kwargs
        assert kwargs["name"] == SCOUT_SKILL_NAME
        assert kwargs["source_product"] == SCOUT_SOURCE_PRODUCT
        assert kwargs["source_id"] == str(self.team.id)
        assert kwargs["config_options"]["run_interval_minutes"] == 60
        assert kwargs["config_options"]["auto_pause_exempt"] is True
        assert "# Signals scout: ticket patterns" in kwargs["body"]
        assert response.json()["enabled"] is True

    def test_enable_twice_re_enables_the_existing_scout_and_syncs_its_body(self):
        with (
            patch(f"{FACADE}.scout_for_source", side_effect=[_scout(enabled=False), _scout()]),
            patch(f"{FACADE}.update_scout_for_source", return_value=True) as update,
            patch(f"{FACADE}.sync_scout_definition_for_source", return_value=True) as sync,
            patch(f"{FACADE}.create_scout_for_source") as create,
        ):
            response = self.client.post(self.url, {}, format="json")

        assert response.status_code == status.HTTP_200_OK
        create.assert_not_called()
        assert update.call_args.kwargs["enabled"] is True
        assert "# Signals scout: ticket patterns" in sync.call_args.kwargs["body"]

    def test_enable_recreates_the_scout_when_its_skill_is_gone(self):
        with (
            patch(f"{FACADE}.scout_for_source", side_effect=[_scout(skill_exists=False), _scout()]),
            patch(f"{FACADE}.create_scout_for_source") as create,
        ):
            create.return_value = ScoutCreated(skill=None, config=None, created=True)
            response = self.client.post(self.url, {}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        create.assert_called_once()

    def test_status_calls_an_orphaned_config_off(self):
        with patch(f"{FACADE}.scout_for_source", return_value=_scout(skill_exists=False)):
            response = self.client.get(f"{self.url}status/")

        assert response.json()["enabled"] is False
        assert response.json()["skill_name"] is None

    def test_enable_is_refused_while_detection_is_off(self):
        self.team.conversations_settings = {"pattern_detection_enabled": False}
        self.team.save()

        with patch(f"{FACADE}.create_scout_for_source") as create:
            response = self.client.post(self.url, {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        create.assert_not_called()

    def test_a_child_environment_stamps_the_scout_with_the_project_team(self):
        child = Team.objects.create(
            organization=self.organization,
            project=self.team.project,
            parent_team=self.team,
            name="staging",
            conversations_enabled=True,
            conversations_settings={"pattern_detection_enabled": True},
        )
        with (
            patch(f"{FACADE}.scout_for_source", side_effect=[None, _scout()]) as lookup,
            patch(f"{FACADE}.create_scout_for_source") as create,
        ):
            create.return_value = ScoutCreated(skill=None, config=None, created=True)
            response = self.client.post(f"/api/projects/{child.id}/conversations/pattern_ai_scan/", {}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert lookup.call_args_list[0].args == (self.team.id, SCOUT_SOURCE_PRODUCT, str(self.team.id))
        assert create.call_args.kwargs["team"] == self.team
        assert create.call_args.kwargs["source_id"] == str(self.team.id)

    def test_enable_without_ai_consent_is_refused_before_touching_signals(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        with patch(f"{FACADE}.create_scout_for_source") as create:
            response = self.client.post(self.url, {}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        create.assert_not_called()

    def test_disable_pauses_rather_than_deletes(self):
        with (
            patch(f"{FACADE}.scout_for_source", return_value=_scout()),
            patch(f"{FACADE}.update_scout_for_source", return_value=True) as update,
        ):
            response = self.client.post(f"{self.url}disable/", {}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert update.call_args.kwargs["enabled"] is False

    def test_reports_come_from_this_source_only(self):
        report = ScoutReport(
            report_id="r1",
            skill_name=SCOUT_SKILL_NAME,
            filed_at=datetime(2026, 7, 25, 10, 5, tzinfo=UTC),
            title="Login failures after password reset",
            summary="Six customers since 09:12.",
            charts=[],
        )
        with patch(f"{FACADE}.scout_reports_for_source", return_value=[report]) as reports:
            response = self.client.get(f"{self.url}reports/")

        assert reports.call_args.args == (self.team.id, SCOUT_SOURCE_PRODUCT, str(self.team.id))
        assert [r["title"] for r in response.json()] == ["Login failures after password reset"]

    def _use_key(self, scopes: list[str]) -> None:
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="scan", user=self.user, secure_value=hash_key_value(raw_key), scopes=scopes)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")

    @parameterized.expand(
        [
            ("status_read_key", "get", "status/", ["ticket:read"], status.HTTP_200_OK),
            ("reports_read_key", "get", "reports/", ["ticket:read"], status.HTTP_200_OK),
            ("enable_ticket_only", "post", "", ["ticket:write"], status.HTTP_403_FORBIDDEN),
            ("disable_ticket_only", "post", "disable/", ["ticket:write"], status.HTTP_403_FORBIDDEN),
            (
                "enable_all_three",
                "post",
                "",
                ["ticket:write", "llm_skill:write", "signal_scout:write"],
                status.HTTP_200_OK,
            ),
        ]
    )
    def test_api_key_scopes(self, _name, method, suffix, scopes, expected):
        self._use_key(scopes)
        with (
            patch(f"{FACADE}.scout_for_source", return_value=_scout()),
            patch(f"{FACADE}.scout_reports_for_source", return_value=[]),
            patch(f"{FACADE}.sync_scout_definition_for_source", return_value=True),
            patch(f"{FACADE}.update_scout_for_source", return_value=True),
        ):
            response = getattr(self.client, method)(f"{self.url}{suffix}", {}, format="json")

        assert response.status_code == expected, response.content

    @parameterized.expand([("status", "get", "status/"), ("reports", "get", "reports/"), ("enable", "post", "")])
    def test_a_member_denied_any_ticket_cannot_use_the_scan(self, _name, method, suffix):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        AccessControl.objects.create(
            resource="ticket",
            resource_id="019f9582-0000-7000-8000-0000000000aa",
            organization_member=self.organization_membership,
            team=self.team,
            access_level="none",
        )

        response = getattr(self.client, method)(f"{self.url}{suffix}", {}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
