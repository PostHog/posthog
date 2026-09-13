from __future__ import annotations

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.conversations.backend.models import TicketTopicOverride


class TestTicketTopicOverrideAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/conversations/pattern_overrides/"

    @parameterized.expand(
        [
            ("case_and_plural_fold", "Login Failures", "login failur"),
            ("stopwords_drop", "the export is broken", "export broken"),
        ]
    )
    def test_topic_is_stored_the_way_detection_will_compare_it(self, _name, typed, stored):
        response = self.client.post(self.url, {"kind": "mute", "topic": typed}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["topic"] == stored

    @parameterized.expand(
        [
            ("no_usable_word", "the and"),
            ("more_than_two_usable_words", "export fails on mobile"),
        ]
    )
    def test_a_topic_detection_cannot_hold_is_rejected(self, _name, typed):
        response = self.client.post(self.url, {"kind": "mute", "topic": typed}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert TicketTopicOverride.objects.for_team(self.team.id).count() == 0

    def test_one_override_per_topic(self):
        self.client.post(self.url, {"kind": "mute", "topic": "billing"}, format="json")

        response = self.client.post(self.url, {"kind": "watch", "topic": "Billing"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert TicketTopicOverride.objects.for_team(self.team.id).count() == 1

    def test_a_ticket_viewer_can_list_but_not_write(self):
        TicketTopicOverride.objects.for_team(self.team.id).create(team=self.team, kind="mute", topic="billing")
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(resource="ticket", team=self.team, access_level="viewer")

        listed = self.client.get(self.url)
        created = self.client.post(self.url, {"kind": "mute", "topic": "export"}, format="json")

        assert [o["topic"] for o in listed.json()["results"]] == ["billing"]
        assert created.status_code == status.HTTP_403_FORBIDDEN
