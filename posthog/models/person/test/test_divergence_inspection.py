import json
from io import StringIO
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.core.management import call_command

from posthog.models.activity_logging.activity_log import ActivityLog, Detail
from posthog.models.person.divergence.inspection import hash_distinct_id, inspect_mappings, inspect_persons
from posthog.models.person.test.divergence_fixtures import DivergenceFixturesMixin
from posthog.models.person.util import tombstone_persons_in_postgres
from posthog.personhog_client.fake_client import get_active_fake


class TestDivergenceInspection(DivergenceFixturesMixin, ClickhouseTestMixin, BaseTest):
    def _log_person_activity(self, activity: str, *, item_id: int, name: str | None) -> None:
        ActivityLog.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.pk,
            item_id=str(item_id),
            scope="Person",
            activity=activity,
            detail=Detail(name=name),
        )

    def _flavors(self, inspections) -> dict[str, tuple[str, str | None, str | None]]:
        return {i.key: (i.flavor, i.sub_flavor, i.verb) for i in inspections}

    def test_inspect_persons_reads_both_stores_into_each_flavor(self):
        tie = self._pg_person(version=2)
        self._ch_person(str(tie.uuid), 2, {"email": "one@example.com"})
        self._ch_person(str(tie.uuid), 2, {"email": "two@example.com"})
        blanked = self._pg_person(version=105)
        self._ch_person(str(blanked.uuid), 1, {"email": "kept@example.com"})
        self._ch_person(str(blanked.uuid), 105, {})
        deleted = self._pg_person(version=2)
        tombstone_persons_in_postgres(self.team.pk, [deleted.uuid])
        self._ch_person(str(deleted.uuid), 7, {"email": "old@example.com"})
        stale = self._pg_person(version=1)
        self._ch_person(str(stale.uuid), 40, {"email": "old@example.com"})
        ghost = str(uuid4())
        self._ch_person(ghost, 3, {"email": "ghost@example.com"})

        self._log_person_activity("deleted", item_id=deleted.pk, name=str(deleted.uuid))
        self._log_person_activity("updated", item_id=stale.pk, name=None)
        self._log_person_activity("updated", item_id=tie.pk, name=None)

        inspections = inspect_persons(
            self.team.pk, [str(p.uuid) for p in (tie, blanked, deleted)] + [str(stale.uuid).upper(), ghost]
        )
        by_key = {i.key: i for i in inspections}
        flavors = self._flavors(inspections)

        assert [(r["version"], r["properties_bytes"] > 2) for r in by_key[str(blanked.uuid)].ch_history or []] == [
            (1, True),
            (105, False),
        ]
        assert [a["activity"] for a in by_key[str(deleted.uuid)].activity or []] == ["deleted"]
        assert [a["activity"] for a in by_key[str(stale.uuid)].activity or []] == ["updated"]
        assert by_key[ghost].activity == []
        queued = by_key[str(deleted.uuid)].tombstone_queue
        assert queued is not None and queued["person_version"] == 3 and queued["tombstoned_at_ms"] > 0
        assert by_key[str(stale.uuid)].tombstone_queue is None
        assert flavors == {
            str(tie.uuid): ("tie", None, "republish"),
            str(blanked.uuid): ("blanked", None, "republish"),
            str(deleted.uuid): ("deleted_visible", None, "bury"),
            str(stale.uuid): ("stale", None, "merge_stale"),
            ghost: ("ghost", "historical", None),
        }

    def test_inspect_mappings_dates_owners_and_finds_strays(self):
        self._pg_person(version=0, distinct_ids=["moved"])
        old_owner = str(uuid4())
        self._ch_mapping("moved", old_owner, 5)
        fake = get_active_fake()
        assert fake is not None
        deleted = fake.add_person(
            team_id=self.team.pk,
            person_id=990_001,
            uuid=str(uuid4()),
            version=3,
            is_deleted=True,
            distinct_ids=["stray"],
        )
        self._ch_mapping("stray", deleted.uuid, 0)

        flavors = self._flavors(inspect_mappings(self.team.pk, ["moved", "stray"]))

        assert flavors == {
            "moved": ("diverged", "a_absent", "fold"),
            "stray": ("stray", None, None),
        }

    def test_inspect_mappings_leaves_ghosts_of_a_deleted_team_alone(self):
        gone_team_id = self.team.pk + 10_000
        self._ch_mapping("gone", str(uuid4()), 4, team_id=gone_team_id)

        assert self._flavors(inspect_mappings(gone_team_id, ["gone"])) == {"gone": ("ghost", "team_gone", None)}

    def test_command_prints_one_json_row_per_key_with_hashed_distinct_ids(self):
        person = self._pg_person(version=2, distinct_ids=["secret-did-7f3a"])
        self._ch_person(str(person.uuid), 2, {"email": "pg@example.com"})
        self._ch_mapping("secret-did-7f3a", str(person.uuid), 0)
        out = StringIO()

        call_command(
            "person_inspect",
            "--team-id",
            str(self.team.pk),
            "--person-uuid",
            str(person.uuid),
            "--distinct-id",
            "secret-did-7f3a",
            stdout=out,
        )

        rows = [json.loads(line) for line in out.getvalue().splitlines()]
        assert [(r["kind"], r["key"], r["flavor"]) for r in rows] == [
            ("person", str(person.uuid), "ok"),
            ("mapping", hash_distinct_id(self.team.pk, "secret-did-7f3a"), "ok"),
        ]
        assert "secret-did-7f3a" not in out.getvalue()
