import uuid
from unittest import mock

from posthog.models import Team
from posthog.test.base import ClickhouseTestMixin, APIBaseTest, _create_person, _create_event, flush_persons_and_events
from rest_framework import status


class TestPersonCommunication(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        _create_person(
            properties={"email": "samir@posthog.com"},
            team=self.team,
            distinct_ids=["2", "some-random-uid"],
            is_identified=True,
        )

        self.bug_report_uuid = str(uuid.uuid4())

        _create_event(
            event="$bug_report",
            event_uuid=self.bug_report_uuid,
            team=self.team,
            distinct_id="2",
            properties={"email": "reporter@reporting.com", "$bug": "the original report"},
        )

        _create_event(
            event="$communication_email_sent",
            team=self.team,
            distinct_id=2,
            properties={"bug_report_uuid": self.bug_report_uuid, "body_plain": "hello world"},
        )

        _create_event(
            event="$communication_email_received",
            team=self.team,
            distinct_id=2,
            properties={"bug_report_uuid": self.bug_report_uuid, "body_html": "<p>hello world</p>"},
        )

        _create_event(
            event="$communication_note_saved",
            team=self.team,
            distinct_id=2,
            properties={"bug_report_uuid": self.bug_report_uuid, "body_html": "<p>hello world</p>"},
        )

        flush_persons_and_events()

    def test_view_communications_by_bug_report_when_there_are_none(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/person_communications/?bug_report_uuid=" + str(uuid.uuid4())
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}

    def test_view_communications_by_bug_report(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/person_communications/?bug_report_uuid=" + self.bug_report_uuid
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == [
            {
                "body_html": "<p>hello world</p>",
                "body_plain": "",
                "bug_report_uuid": self.bug_report_uuid,
                "event": "$communication_note_saved",
                "from": "",
                "subject": "",
                "email": "reporter@reporting.com",
                "timestamp": mock.ANY,
                "to": "",
            },
            {
                "body_html": "<p>hello world</p>",
                "body_plain": "",
                "bug_report_uuid": self.bug_report_uuid,
                "event": "$communication_email_received",
                "from": "",
                "subject": "",
                "email": "reporter@reporting.com",
                "timestamp": mock.ANY,
                "to": "",
            },
            {
                "body_html": "",
                "body_plain": "hello world",
                "bug_report_uuid": self.bug_report_uuid,
                "event": "$communication_email_sent",
                "from": "",
                "subject": "",
                "email": "reporter@reporting.com",
                "timestamp": mock.ANY,
                "to": "",
            },
            {
                "body_html": "",
                "body_plain": "the original report",
                "bug_report_uuid": "",
                "email": "reporter@reporting.com",
                "event": "$bug_report",
                "from": "",
                "subject": "",
                "timestamp": mock.ANY,
                "to": "",
            },
        ]

    def test_cannot_view_another_team_communications(self) -> None:
        another_team = Team.objects.create(organization=self.organization)

        response = self.client.get(
            f"/api/projects/{another_team.id}/person_communications/?bug_report_uuid=" + str(uuid.uuid4())
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
