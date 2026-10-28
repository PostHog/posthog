from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from posthog.models import ActivityLog, Team
from posthog.models.event_filter_config import EventFilterConfig, EventFilterMode

from ee.models.event_definition import EnterpriseEventDefinition
from ee.tasks.event_definitions import GIVE_UP_AFTER, TRIGGER_JOB_TYPE, delete_scheduled_event_definitions


def _drop_tree(event_name: str) -> dict:
    return {
        "type": "or",
        "children": [{"type": "condition", "field": "event_name", "operator": "exact", "value": event_name}],
    }


class TestDeleteScheduledEventDefinitions(ClickhouseTestMixin, BaseTest):
    def _scheduled_definition(self, due_since: timedelta = timedelta(minutes=5), **kwargs) -> EnterpriseEventDefinition:
        return EnterpriseEventDefinition.objects.create(
            team=self.team,
            project=self.project,
            name="spam_event",
            hidden=True,
            scheduled_deletion_at=timezone.now() - due_since,
            **kwargs,
        )

    def _drop_in(self, team: Team, event_name: str = "spam_event") -> None:
        EventFilterConfig.objects.create(team=team, mode=EventFilterMode.LIVE, filter_tree=_drop_tree(event_name))

    def _ingest(self, team: Team, ingested_ago: timedelta) -> None:
        now = timezone.now()
        _create_event(team=team, event="spam_event", distinct_id="user", timestamp=now, _timestamp=now - ingested_ago)
        flush_persons_and_events()

    def test_deletes_a_due_definition_and_logs_activity(self):
        definition = self._scheduled_definition()
        self._drop_in(self.team)

        delete_scheduled_event_definitions()

        assert not EnterpriseEventDefinition.objects.filter(pk=definition.pk).exists()
        log = ActivityLog.objects.get(team_id=self.team.id, scope="EventDefinition", item_id=str(definition.id))
        assert log.activity == "deleted"
        assert log.user is None
        assert log.detail is not None
        assert log.detail["name"] == "spam_event"
        assert log.detail["trigger"]["job_type"] == TRIGGER_JOB_TYPE

    def test_deletes_when_the_only_events_are_older_than_the_window(self):
        definition = self._scheduled_definition()
        self._drop_in(self.team)
        self._ingest(self.team, ingested_ago=timedelta(hours=3))

        delete_scheduled_event_definitions()

        assert not EnterpriseEventDefinition.objects.filter(pk=definition.pk).exists()

    def test_keeps_a_definition_that_is_not_due(self):
        definition = self._scheduled_definition(due_since=-timedelta(minutes=5))
        self._drop_in(self.team)

        delete_scheduled_event_definitions()

        assert EnterpriseEventDefinition.objects.filter(pk=definition.pk).exists()

    def test_tries_again_later_when_the_event_is_no_longer_dropped(self):
        definition = self._scheduled_definition()
        EventFilterConfig.objects.create(
            team=self.team, mode=EventFilterMode.DRY_RUN, filter_tree=_drop_tree("spam_event")
        )

        delete_scheduled_event_definitions()

        definition.refresh_from_db()
        assert definition.scheduled_deletion_at is not None

    def test_tries_again_later_when_an_event_arrived_recently(self):
        definition = self._scheduled_definition()
        self._drop_in(self.team)
        self._ingest(self.team, ingested_ago=timedelta(minutes=10))

        delete_scheduled_event_definitions()

        definition.refresh_from_db()
        assert definition.scheduled_deletion_at is not None

    def test_checks_every_environment_in_the_project(self):
        other_team = Team.objects.create(organization=self.organization, project=self.project, name="Staging")
        definition = self._scheduled_definition()
        self._drop_in(self.team)
        self._drop_in(other_team)
        self._ingest(other_team, ingested_ago=timedelta(minutes=10))

        delete_scheduled_event_definitions()

        assert EnterpriseEventDefinition.objects.filter(pk=definition.pk).exists()

    def test_cancels_when_someone_unhid_the_event(self):
        definition = self._scheduled_definition()
        definition.hidden = False
        definition.save()
        self._drop_in(self.team)

        delete_scheduled_event_definitions()

        definition.refresh_from_db()
        assert definition.scheduled_deletion_at is None

    def test_gives_up_and_keeps_the_event_hidden(self):
        definition = self._scheduled_definition(due_since=GIVE_UP_AFTER + timedelta(minutes=5))

        delete_scheduled_event_definitions()

        definition.refresh_from_db()
        assert definition.scheduled_deletion_at is None
        assert definition.hidden is True
