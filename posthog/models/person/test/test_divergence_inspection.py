import json
from io import StringIO
from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.core.management import call_command
from django.utils.timezone import now

from posthog.clickhouse.client import sync_execute
from posthog.models.person.divergence.inspection import hash_distinct_id, inspect_mappings, inspect_persons
from posthog.models.person.sql import BULK_INSERT_PERSON_DISTINCT_ID2
from posthog.models.person.util import (
    create_person as create_person_in_ch,
    tombstone_persons_in_postgres,
)
from posthog.models.signals import mute_selected_signals
from posthog.personhog_client.fake_client import get_active_fake
from posthog.test.persons import add_distinct_id, create_person


class TestDivergenceInspection(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # A background merge collapses the duplicate and older rows the tie and blanked shapes are made of.
        for table in ("person", "person_distinct_id2"):
            sync_execute(f"SYSTEM STOP MERGES {table}")
            self.addCleanup(sync_execute, f"SYSTEM START MERGES {table}")

    def _pg_person(self, *, version: int, distinct_ids: list[str] | None = None):
        with mute_selected_signals():
            person = create_person(team=self.team, version=version, properties={"email": "pg@example.com"})
            for distinct_id in distinct_ids or []:
                add_distinct_id(person=person, distinct_id=distinct_id, version=0)
        return person

    def _ch_person(self, person_uuid: str, version: int, properties: dict, *, deleted: bool = False) -> None:
        create_person_in_ch(
            team_id=self.team.pk,
            uuid=person_uuid,
            version=version,
            is_deleted=deleted,
            properties=properties,
            timestamp=now(),
        )

    def _ch_mapping(self, distinct_id: str, person_uuid: str, version: int) -> None:
        sync_execute(
            BULK_INSERT_PERSON_DISTINCT_ID2,
            [
                {
                    "distinct_id": distinct_id,
                    "person_id": person_uuid,
                    "team_id": self.team.pk,
                    "is_deleted": 0,
                    "version": version,
                    "_timestamp": now().replace(tzinfo=None),
                    "_offset": 0,
                    "_partition": 0,
                }
            ],
            flush=False,
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

        flavors = self._flavors(
            inspect_persons(self.team.pk, [str(p.uuid) for p in (tie, blanked, deleted, stale)] + [ghost])
        )

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
            "stray": ("stray", None, "detach_stray"),
        }

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
