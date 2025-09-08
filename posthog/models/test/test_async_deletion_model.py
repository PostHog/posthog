import datetime as dt
from uuid import UUID, uuid4

from posthog.test.base import (
    BaseTest,
    ClickhouseDestroyTablesMixin,
    ClickhouseTestMixin,
    _create_event,
    snapshot_clickhouse_alter_queries,
    snapshot_clickhouse_queries,
)

from posthog.clickhouse.client import sync_execute
from posthog.models import AsyncDeletion, DeletionType, Team, User
from posthog.models.async_deletion.delete_cohorts import AsyncCohortDeletion
from posthog.models.async_deletion.delete_events import AsyncEventDeletion
from posthog.models.cohort.util import insert_static_cohort
from posthog.models.group.util import create_group
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.models.plugin import PluginLogEntrySource, PluginLogEntryType
from posthog.test.test_plugin_log_entry import create_plugin_log_entry

uuid = str(UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8"))
uuid2 = str(UUID("7ba7b810-9dad-11d1-80b4-00c04fd430c8"))


class TestAsyncDeletion(ClickhouseTestMixin, ClickhouseDestroyTablesMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create(email="test@posthog.com")
        self.teams = [
            self.team,
            Team.objects.create(organization=self.organization),
            Team.objects.create(organization=self.organization),
        ]

    @snapshot_clickhouse_queries
    def test_mark_team_deletions_done(self):
        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Team,
            team_id=self.teams[0].pk,
            key=str(self.teams[0].pk),
            created_by=self.user,
        )

        AsyncEventDeletion().mark_deletions_done()

        deletion.refresh_from_db()
        self.assertIsNotNone(deletion.delete_verified_at)

    @snapshot_clickhouse_queries
    def test_mark_deletions_done_team_when_not_done(self):
        _create_event(event_uuid=uuid4(), event="event1", team=self.teams[0], distinct_id="1")

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Team,
            team_id=self.teams[0].pk,
            key=str(self.teams[0].pk),
            created_by=self.user,
        )

        AsyncEventDeletion().mark_deletions_done()

        deletion.refresh_from_db()
        self.assertIsNone(deletion.delete_verified_at)

    @snapshot_clickhouse_queries
    def test_mark_deletions_done_person(self):
        base_datetime = dt.datetime(2024, 1, 1, 0, 0, 0, tzinfo=dt.UTC)

        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            person_id=uuid2,
            _timestamp=base_datetime - dt.timedelta(days=1),
        )
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[1],
            distinct_id="1",
            person_id=uuid,
            _timestamp=base_datetime - dt.timedelta(days=1),
        )

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=self.teams[0].pk,
            key=str(uuid),
            created_by=self.user,
        )
        # Adjust `created_at` after creation to get around `auto_now_add`
        deletion.created_at = base_datetime
        deletion.save()

        AsyncEventDeletion().mark_deletions_done()

        deletion.refresh_from_db()
        self.assertIsNotNone(deletion.delete_verified_at)

    @snapshot_clickhouse_queries
    def test_mark_deletions_done_person_when_not_done(self):
        base_datetime = dt.datetime(2024, 1, 1, 0, 0, 0, tzinfo=dt.UTC)

        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            person_id=uuid,
            _timestamp=base_datetime - dt.timedelta(days=1),
        )

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=self.teams[0].pk,
            key=str(uuid),
            created_by=self.user,
        )
        # Adjust `created_at` after creation to get around `auto_now_add`
        deletion.created_at = base_datetime
        deletion.save()

        AsyncEventDeletion().mark_deletions_done()

        deletion.refresh_from_db()
        self.assertIsNone(deletion.delete_verified_at)

    @snapshot_clickhouse_queries
    def test_mark_deletions_done_groups(self):
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            properties={"$group_1": "foo"},
        )
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            properties={"$group_0": "bar"},
        )
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[1],
            distinct_id="1",
            properties={"$group_0": "foo"},
        )

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Group,
            team_id=self.teams[0].pk,
            group_type_index=0,
            key="foo",
            created_by=self.user,
        )

        AsyncEventDeletion().mark_deletions_done()

        deletion.refresh_from_db()
        self.assertIsNotNone(deletion.delete_verified_at)

    @snapshot_clickhouse_queries
    def test_mark_deletions_done_groups_when_not_done(self):
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            properties={"$group_0": "foo"},
        )

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Group,
            team_id=self.teams[0].pk,
            group_type_index=0,
            key="foo",
            created_by=self.user,
        )

        AsyncEventDeletion().mark_deletions_done()

        deletion.refresh_from_db()
        self.assertIsNone(deletion.delete_verified_at)

    @snapshot_clickhouse_alter_queries
    def test_delete_teams(self):
        _create_event(event_uuid=uuid4(), event="event1", team=self.teams[0], distinct_id="1")
        _create_event(event_uuid=uuid4(), event="event2", team=self.teams[1], distinct_id="2")

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Team,
            team_id=self.teams[0].pk,
            key=str(self.teams[0].pk),
            created_by=self.user,
        )
        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Team,
            team_id=self.teams[1].pk,
            key=str(self.teams[1].pk),
            created_by=self.user,
        )

        AsyncEventDeletion().run()

        self.assertRowCount(0)

    @snapshot_clickhouse_alter_queries
    def test_delete_teams_unrelated(self):
        _create_event(event_uuid=uuid4(), event="event1", team=self.teams[1], distinct_id="1")

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Team,
            team_id=self.teams[0].pk,
            key=str(self.teams[0].pk),
            created_by=self.user,
        )

        AsyncEventDeletion().run()

        self.assertRowCount(1)

    @snapshot_clickhouse_alter_queries
    def test_delete_person(self):
        base_datetime = dt.datetime(2024, 1, 1, 0, 0, 0, tzinfo=dt.UTC)

        # Event for person, created before AsyncDeletion, so it should be deleted
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            person_id=uuid,
            _timestamp=base_datetime - dt.timedelta(days=1),
        )

        # Event for person, created after AsyncDeletion, so it should be left behind
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            person_id=uuid,
            _timestamp=base_datetime + dt.timedelta(days=1),
        )

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=self.teams[0].pk,
            key=str(uuid),
            created_by=self.user,
        )
        # Adjust `created_at` after creation to get around `auto_now_add`
        deletion.created_at = base_datetime
        deletion.save()

        AsyncEventDeletion().run()

        self.assertRowCount(1)

    @snapshot_clickhouse_alter_queries
    def test_delete_person_unrelated(self):
        base_datetime = dt.datetime(2024, 1, 1, 0, 0, 0, tzinfo=dt.UTC)

        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            person_id=uuid2,
            _timestamp=base_datetime - dt.timedelta(days=1),
        )
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[1],
            distinct_id="1",
            person_id=uuid,
            _timestamp=base_datetime - dt.timedelta(days=1),
        )

        deletion = AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=self.teams[0].pk,
            key=str(uuid),
            created_by=self.user,
        )
        # Adjust `created_at` after creation to get around `auto_now_add`
        deletion.created_at = base_datetime
        deletion.save()

        AsyncEventDeletion().run()

        self.assertRowCount(2)

    @snapshot_clickhouse_alter_queries
    def test_delete_group(self):
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            properties={"$group_0": "foo"},
        )

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Group,
            team_id=self.teams[0].pk,
            group_type_index=0,
            key="foo",
            created_by=self.user,
        )

        AsyncEventDeletion().run()

        self.assertRowCount(0)

    @snapshot_clickhouse_alter_queries
    def test_delete_group_unrelated(self):
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            properties={"$group_1": "foo"},
        )
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[0],
            distinct_id="1",
            properties={"$group_0": "bar"},
        )
        _create_event(
            event_uuid=uuid4(),
            event="event1",
            team=self.teams[1],
            distinct_id="1",
            properties={"$group_0": "foo"},
        )

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Group,
            team_id=self.teams[0].pk,
            group_type_index=0,
            key="foo",
            created_by=self.user,
        )

        AsyncEventDeletion().run()

        self.assertRowCount(3)

    @snapshot_clickhouse_alter_queries
    def test_delete_auxilary_models_via_team(self):
        create_person(team_id=self.teams[0].pk, properties={"x": 0}, version=0, uuid=uuid)
        create_person_distinct_id(self.teams[0].pk, "0", uuid)
        create_group(
            team_id=self.teams[0].pk,
            group_type_index=0,
            group_key="org:5",
            properties={},
        )
        insert_static_cohort([uuid4()], 0, team_id=self.teams[0].pk)
        self._insert_cohortpeople_row(self.teams[0], uuid4(), 3)
        create_plugin_log_entry(
            team_id=self.teams[0].pk,
            plugin_id=1,
            plugin_config_id=1,
            source=PluginLogEntrySource.SYSTEM,
            type=PluginLogEntryType.INFO,
            message="Hello world",
            instance_id=uuid,
        )

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Team,
            team_id=self.teams[0].pk,
            key=str(self.teams[0].pk),
            created_by=self.user,
        )
        AsyncEventDeletion().run()

        self.assertRowCount(0, "person")
        self.assertRowCount(0, "person_distinct_id")
        self.assertRowCount(0, "person_distinct_id2")
        self.assertRowCount(0, "groups")
        self.assertRowCount(0, "cohortpeople")
        self.assertRowCount(0, "person_static_cohort")
        self.assertRowCount(0, "plugin_log_entries")

    @snapshot_clickhouse_alter_queries
    def test_delete_auxilary_models_via_team_unrelated(self):
        create_person(team_id=self.teams[1].pk, properties={"x": 0}, version=0, uuid=uuid)
        create_person_distinct_id(self.teams[1].pk, "0", uuid)
        create_group(
            team_id=self.teams[1].pk,
            group_type_index=0,
            group_key="org:5",
            properties={},
        )
        insert_static_cohort([uuid4()], 0, team_id=self.teams[1].pk)
        self._insert_cohortpeople_row(self.teams[1], uuid4(), 3)
        create_plugin_log_entry(
            team_id=self.teams[1].pk,
            plugin_id=1,
            plugin_config_id=1,
            source=PluginLogEntrySource.SYSTEM,
            type=PluginLogEntryType.INFO,
            message="Hello world",
            instance_id=uuid,
        )

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Team,
            team_id=self.teams[0].pk,
            key=str(self.teams[0].pk),
            created_by=self.user,
        )
        AsyncEventDeletion().run()

        self.assertRowCount(1, "person")
        self.assertRowCount(1, "person_distinct_id2")
        self.assertRowCount(1, "groups")
        self.assertRowCount(1, "cohortpeople")
        self.assertRowCount(1, "person_static_cohort")
        self.assertRowCount(1, "plugin_log_entries")

    @snapshot_clickhouse_queries
    def test_delete_cohortpeople(self):
        cohort_id = 3
        team = self.teams[0]
        self._insert_cohortpeople_row(team, uuid4(), cohort_id)

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Cohort_full,
            team_id=team.pk,
            key=str(cohort_id) + "_0",
            created_by=self.user,
        )
        AsyncCohortDeletion().run()

        self.assertRowCount(0, "cohortpeople")

    @snapshot_clickhouse_queries
    def test_delete_cohortpeople_version(self):
        cohort_id = 3
        team = self.teams[0]
        self._insert_cohortpeople_row(team, uuid4(), cohort_id, 2)
        self._insert_cohortpeople_row(team, uuid4(), cohort_id, 3)

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Cohort_stale,
            team_id=team.pk,
            key=str(cohort_id) + "_3",
            created_by=self.user,
        )
        AsyncCohortDeletion().run()

        self.assertRowCount(1, "cohortpeople")

    def assertRowCount(self, expected, table="events"):
        result = sync_execute(f"SELECT count() FROM {table}")[0][0]
        self.assertEqual(result, expected)

    def _insert_cohortpeople_row(self, team: Team, person_id: UUID, cohort_id: int, version: int = 0):
        sync_execute(
            f"""
            INSERT INTO cohortpeople (person_id, cohort_id, team_id, sign, version)
            VALUES (%(person_id)s, %(cohort_id)s, %(team_id)s, 1, %(version)s)
            """,
            {
                "person_id": str(person_id),
                "cohort_id": cohort_id,
                "team_id": team.pk,
                "version": version,
            },
        )
