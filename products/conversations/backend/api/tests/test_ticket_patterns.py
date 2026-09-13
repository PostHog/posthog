from __future__ import annotations

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.conversations.backend.models import (
    Ticket,
    TicketPattern,
    TicketPatternEvidence,
    TicketPatternStatus,
    TicketTopicBaseline,
)


class TestTicketPatternAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base_url = f"/api/projects/{self.team.id}/conversations/patterns/"
        now = timezone.now()
        self.pattern = TicketPattern.objects.for_team(self.team.id).create(
            team=self.team,
            fingerprint="terms:login",
            topic="login",
            title="6 tickets from 6 customers about: login",
            ticket_count=6,
            requester_count=6,
            peak_ticket_count=6,
            opened_at=now,
            last_seen_at=now,
        )
        self.tickets = [
            Ticket.objects.create(team=self.team, ticket_number=i + 1, channel_source="email", email_subject="login")
            for i in range(2)
        ]
        TicketPatternEvidence.objects.for_team(self.team.id).bulk_create(
            [TicketPatternEvidence(team=self.team, pattern=self.pattern, ticket=t) for t in self.tickets]
        )
        TicketTopicBaseline.objects.for_team(self.team.id).create(team=self.team, topic="login", refreshed_at=now)

    def _url(self, suffix: str = "") -> str:
        return f"{self.base_url}{self.pattern.id}/{suffix}"

    @parameterized.expand(
        [
            ("confirm", TicketPatternStatus.CONFIRMED, "confirm_count", {"severity": "high"}),
            ("dismiss", TicketPatternStatus.DISMISSED, "dismiss_count", {"reason": "maintenance window"}),
        ]
    )
    def test_transition_records_feedback_on_the_topic_baseline(self, action, expected_status, counter, body):
        response = self.client.post(self._url(f"{action}/"), body, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == expected_status
        assert response.json()["resolved_by"]["id"] == self.user.id
        baseline = TicketTopicBaseline.objects.for_team(self.team.id).get(topic="login")
        assert getattr(baseline, counter) == 1

    @parameterized.expand([("confirm", "confirm_count"), ("dismiss", "dismiss_count")])
    def test_transition_records_feedback_when_the_topic_has_no_baseline(self, action, counter):
        TicketTopicBaseline.objects.for_team(self.team.id).filter(topic="login").delete()

        response = self.client.post(self._url(f"{action}/"), {}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        baseline = TicketTopicBaseline.objects.for_team(self.team.id).get(topic="login")
        assert getattr(baseline, counter) == 1

    def test_an_oversized_limit_is_capped(self):
        now = timezone.now()
        TicketPattern.objects.for_team(self.team.id).bulk_create(
            [
                TicketPattern(
                    team=self.team,
                    fingerprint=f"terms:bulk{i}",
                    topic=f"bulk{i}",
                    title=f"pattern {i}",
                    ticket_count=5,
                    requester_count=5,
                    peak_ticket_count=5,
                    opened_at=now,
                    last_seen_at=now,
                )
                for i in range(100)
            ]
        )

        response = self.client.get(f"{self.base_url}?limit=1000")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(response.json()["results"]) == 100
        assert response.json()["count"] == 101

    def test_confirm_records_severity_and_owner(self):
        response = self.client.post(self._url("confirm/"), {"severity": "critical"}, format="json")

        assert response.json()["severity"] == "critical"
        assert response.json()["owner"]["id"] == self.user.id

    def test_dismiss_reason_lands_in_evidence(self):
        response = self.client.post(self._url("dismiss/"), {"reason": "planned outage"}, format="json")

        assert response.json()["evidence"]["dismiss_reason"] == "planned outage"

    def test_a_resolved_pattern_cannot_be_transitioned_again(self):
        self.client.post(self._url("dismiss/"), {}, format="json")

        response = self.client.post(self._url("confirm/"), {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        self.pattern.refresh_from_db()
        assert self.pattern.status == TicketPatternStatus.DISMISSED

    def _restrict_one_ticket(self) -> None:
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            resource="ticket",
            resource_id=str(self.tickets[0].id),
            organization_member=self.organization_membership,
            team=self.team,
            access_level="none",
        )

    def test_a_member_denied_any_ticket_sees_no_patterns(self):
        # The topic is built from ticket text and the counts span the whole inbox, so a partial view
        # of the tickets cannot come with a full view of their patterns.
        self._restrict_one_ticket()

        listed = self.client.get(self.base_url)
        retrieved = self.client.get(self._url())
        by_ticket = self.client.get(self.base_url, {"ticket_id": str(self.tickets[0].id)})

        assert listed.json()["results"] == []
        assert retrieved.status_code == status.HTTP_404_NOT_FOUND
        assert by_ticket.json()["results"] == []

    @parameterized.expand([("confirm",), ("dismiss",)])
    def test_a_member_denied_any_ticket_cannot_transition_a_pattern(self, action):
        self._restrict_one_ticket()

        response = self.client.post(self._url(f"{action}/"), {}, format="json")

        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        self.pattern.refresh_from_db()
        assert self.pattern.status == TicketPatternStatus.OPEN

    def test_a_ticket_viewer_can_read_but_not_transition(self):
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(resource="ticket", team=self.team, access_level="viewer")

        listed = self.client.get(self.base_url)
        confirmed = self.client.post(self._url("confirm/"), {}, format="json")

        assert [p["topic"] for p in listed.json()["results"]] == ["login"]
        assert confirmed.status_code == status.HTTP_403_FORBIDDEN
        self.pattern.refresh_from_db()
        assert self.pattern.status == TicketPatternStatus.OPEN

    def test_list_filters_by_status_and_ticket(self):
        TicketPattern.objects.for_team(self.team.id).create(
            team=self.team,
            fingerprint="terms:export",
            topic="export",
            title="export",
            status=TicketPatternStatus.RESOLVED,
            opened_at=timezone.now(),
            last_seen_at=timezone.now(),
        )

        open_only = self.client.get(self.base_url, {"status": "open"}).json()["results"]
        by_ticket = self.client.get(self.base_url, {"ticket_id": str(self.tickets[0].id)}).json()["results"]

        assert [p["topic"] for p in open_only] == ["login"]
        assert [p["topic"] for p in by_ticket] == ["login"]

    @parameterized.expand(
        [
            ("ticket_id", {"ticket_id": "not-a-uuid"}),
            ("status", {"status": "open,bogus"}),
        ]
    )
    def test_a_bad_filter_value_is_rejected(self, _name, params):
        response = self.client.get(self.base_url, params)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_patterns_from_another_environment_are_not_listed(self):
        sibling = type(self.team).objects.create(organization=self.organization, project=self.team.project)
        TicketPattern.objects.for_team(sibling.id).create(
            team=sibling,
            fingerprint="terms:billing",
            topic="billing",
            title="billing",
            opened_at=timezone.now(),
            last_seen_at=timezone.now(),
        )

        response = self.client.get(self.base_url).json()["results"]

        assert [p["topic"] for p in response] == ["login"]
