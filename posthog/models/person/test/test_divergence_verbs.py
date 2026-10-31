import os
import json
import shutil
import signal
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from confluent_kafka import KafkaError
from parameterized import parameterized

from posthog.kafka_client.client import ClickhouseProducer, ProduceResult
from posthog.kafka_client.topics import KAFKA_PERSON
from posthog.models.person.divergence import repairs, team_scan, verbs
from posthog.models.person.test.divergence_fixtures import DivergenceFixturesMixin
from posthog.models.person.util import tombstone_persons_in_postgres
from posthog.personhog_client.fake_client import get_active_fake


class _Stop(Exception):
    pass


class TestRepairVerbs(DivergenceFixturesMixin, ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.scans = 0

    def _scan(self) -> tuple[Path, dict[str, tuple[str, str | None]]]:
        self.scans += 1
        scan_dir = self.root / f"scan-{self.scans}"
        team_scan.create_plan(scan_dir, self.team.pk)
        team_scan.run_chunk(scan_dir, 0, resume=False)
        team_scan.run_postgres(scan_dir, resume=False)
        team_scan.finalize(scan_dir)
        rows = [json.loads(line) for line in (scan_dir / team_scan.REPORT_FILE).read_text().splitlines()]
        return scan_dir, {r["key"]: (r["flavor"], r["verb"]) for r in rows}

    def _run(self, scan_dir: Path, verb: str, *, apply: bool, name: str = "actions", **kwargs: Any) -> list[dict]:
        actions_path = scan_dir / f"{name}-{verb}.jsonl"
        verbs.run_verb(scan_dir, verb, apply=apply, actions_path=actions_path, **kwargs)
        return [json.loads(line) for line in actions_path.read_text().splitlines()]

    def _mapped_person(self, version: int):
        distinct_id = f"did-{uuid4()}"
        person = self._pg_person(version=version, distinct_ids=[distinct_id])
        self._ch_mapping(distinct_id, str(person.uuid), 0)
        return person

    def _person_with_ch(self, version: int, distinct_ids: list[str] | None = None):
        person = self._pg_person(version=version, distinct_ids=distinct_ids)
        self._ch_person(str(person.uuid), version, {"email": "pg@example.com"})
        for distinct_id in distinct_ids or []:
            self._ch_mapping(distinct_id, str(person.uuid), 0)
        return person

    def test_republish_reports_in_a_dry_run_and_clears_every_row_when_applied(self):
        hidden = self._mapped_person(1)
        self._ch_person(str(hidden.uuid), 1, {"email": "pg@example.com"})
        self._ch_person(str(hidden.uuid), 100, {}, deleted=True)
        blanked = self._mapped_person(105)
        self._ch_person(str(blanked.uuid), 1, {"email": "kept@example.com"})
        self._ch_person(str(blanked.uuid), 105, {})
        tied = self._mapped_person(2)
        self._ch_person(str(tied.uuid), 2, {"email": "one@example.com"})
        self._ch_person(str(tied.uuid), 2, {"email": "two@example.com"})
        owner = self._person_with_ch(1, ["m-stale"])
        self._ch_mapping("m-stale", str(owner.uuid), 5)
        scan_dir, before = self._scan()
        expected = {
            str(hidden.uuid): ("hidden", "republish"),
            str(blanked.uuid): ("blanked", "republish"),
            str(tied.uuid): ("tie", "republish"),
            "m-stale": ("stale", "republish"),
        }
        assert before == expected

        dry = self._run(scan_dir, "republish", apply=False, name="dry")

        assert {a["key"]: a["outcome"] for a in dry if a["outcome"] != "skipped_not_divergent"} == dict.fromkeys(
            expected, "would_repair"
        )
        assert self._scan()[1] == expected

        applied = self._run(scan_dir, "republish", apply=True)

        assert {a["key"]: a["outcome"] for a in applied if a["outcome"] != "skipped_not_divergent"} == dict.fromkeys(
            expected, "repaired"
        )
        assert self._scan()[1] == {}

    def test_resume_skips_keys_an_earlier_run_finished(self):
        first, second = self._mapped_person(1), self._mapped_person(1)
        for person in (first, second):
            self._ch_person(str(person.uuid), 1, {"email": "pg@example.com"})
            self._ch_person(str(person.uuid), 100, {}, deleted=True)
        scan_dir, _ = self._scan()

        canary = self._run(scan_dir, "republish", apply=True, limit=1)
        rest = self._run(scan_dir, "republish", apply=True, resume=True)

        canary_persons = [(a["key"], a["outcome"]) for a in canary if a["kind"] == "person"]
        assert len(canary_persons) == 1 and canary_persons[0][1] == "repaired"
        resumed = [a["key"] for a in rest[len(canary) :] if a["kind"] == "person"]
        assert resumed == [k for k in (str(first.uuid), str(second.uuid)) if k != canary_persons[0][0]]
        assert self._scan()[1] == {}

    def test_bury_tombstones_what_postgres_deleted_and_leaves_strays_to_ingestion(self):
        deleted = self._pg_person(version=2)
        tombstone_persons_in_postgres(self.team.pk, [deleted.uuid])
        self._ch_person(str(deleted.uuid), 7, {"email": "old@example.com"})
        fake = get_active_fake()
        assert fake is not None
        holder = fake.add_person(
            team_id=self.team.pk,
            person_id=990_001,
            uuid=str(uuid4()),
            version=0,
            distinct_ids=["gone", "unpublished", "holder-1"],
            distinct_id_versions={"gone": 3, "unpublished": 3},
            tombstoned_distinct_ids=["gone", "unpublished"],
        )
        self._ch_person(holder.uuid, 0, {})
        self._ch_mapping("gone", holder.uuid, 5)
        self._ch_mapping("unpublished", holder.uuid, 1)
        self._ch_mapping("holder-1", holder.uuid, 0)
        stray_owner = fake.add_person(
            team_id=self.team.pk,
            person_id=990_002,
            uuid=str(uuid4()),
            version=3,
            is_deleted=True,
            distinct_ids=["stray-1"],
        )
        self._ch_mapping("stray-1", stray_owner.uuid, 0)
        scan_dir, before = self._scan()
        assert before == {
            str(deleted.uuid): ("deleted_visible", "bury"),
            "gone": ("deleted_visible", "bury"),
            "unpublished": ("deleted_visible", "bury"),
            "stray-1": ("stray", None),
        }

        buried = self._run(scan_dir, "bury", apply=True)

        assert {a["key"]: a["outcome"] for a in buried} == {
            str(deleted.uuid): "republished",
            "gone": "buried",
            "unpublished": "buried",
        }
        assert self._scan()[1] == {"stray-1": ("stray", None)}

    def _hidden_person_with_stale_mapping(self) -> str:
        person = self._pg_person(version=1, distinct_ids=["h-1"])
        self._ch_person(str(person.uuid), 1, {"email": "pg@example.com"})
        self._ch_person(str(person.uuid), 100, {}, deleted=True)
        self._ch_mapping("h-1", str(person.uuid), 5)
        return str(person.uuid)

    def _tombstoned_mapping_visible_in_ch(self) -> str:
        fake = get_active_fake()
        assert fake is not None
        holder = fake.add_person(
            team_id=self.team.pk,
            person_id=990_003,
            uuid=str(uuid4()),
            version=0,
            distinct_ids=["gone", "holder-1"],
            distinct_id_versions={"gone": 3},
            tombstoned_distinct_ids=["gone"],
        )
        self._ch_person(holder.uuid, 0, {})
        self._ch_mapping("gone", holder.uuid, 5)
        self._ch_mapping("holder-1", holder.uuid, 0)
        return "gone"

    @parameterized.expand(
        [
            ("republish_after_person_raise", "republish", "repairs.raise_person_version"),
            ("republish_after_mapping_raise", "republish", "repairs._raise_mapping_version_floors"),
            ("republish_after_person_publish", "republish", "repairs._publish_person"),
            ("republish_after_mapping_publish", "republish", "repairs.create_person_distinct_id"),
            ("bury_after_mapping_raise", "bury", "repairs._raise_mapping_version_floor"),
            ("bury_after_mapping_publish", "bury", "verbs.create_person_distinct_id"),
        ]
    )
    def test_a_run_stopped_after_any_step_converges_on_rerun(self, _name: str, verb: str, step: str):
        if verb == "republish":
            self._hidden_person_with_stale_mapping()
        else:
            self._tombstoned_mapping_visible_in_ch()
        scan_dir, before = self._scan()
        assert {v for _, v in before.values()} == {verb}
        module, name = step.split(".")
        target = f"posthog.models.person.divergence.{module}.{name}"
        original = getattr({"repairs": repairs, "verbs": verbs}[module], name)

        def step_then_stop(*args: Any, **kwargs: Any) -> Any:
            original(*args, **kwargs)
            raise _Stop

        with patch(target, side_effect=step_then_stop), pytest.raises(_Stop):
            self._run(scan_dir, verb, apply=True)
        self._run(scan_dir, verb, apply=True, resume=True)

        assert self._scan()[1] == {}

    # Republish counts a failed delivery after the run; the orphan repair behind bury raises on it.
    @parameterized.expand([("republish", False), ("bury", True)])
    def test_a_publish_that_did_not_land_is_retried_on_resume(self, verb: str, raises: bool):
        if verb == "republish":
            key = self._hidden_person_with_stale_mapping()
        else:
            deleted = self._pg_person(version=2)
            tombstone_persons_in_postgres(self.team.pk, [deleted.uuid])
            self._ch_person(str(deleted.uuid), 7, {"email": "old@example.com"})
            key = str(deleted.uuid)
        scan_dir, _ = self._scan()
        failed = ProduceResult(topic=KAFKA_PERSON)
        failed.set_result(KafkaError(-192, "Local: Message timed out"), None)
        actions_path = scan_dir / f"{verb}.jsonl"

        with patch.object(ClickhouseProducer, "produce", return_value=failed):
            if raises:
                with pytest.raises(Exception):
                    verbs.run_verb(scan_dir, verb, apply=True, actions_path=actions_path)
            else:
                counts = verbs.run_verb(scan_dir, verb, apply=True, actions_path=actions_path)
                assert counts["undelivered"] > 0
        last = {}
        for action in map(json.loads, actions_path.read_text().splitlines()):
            last[action["key"]] = action["outcome"]
        assert last[key] == "undelivered"

        verbs.run_verb(scan_dir, verb, apply=True, actions_path=actions_path, resume=True)

        assert self._scan()[1] == {}

    def test_a_run_stopped_by_sigterm_records_its_undelivered_keys_for_resume(self):
        key = self._hidden_person_with_stale_mapping()
        scan_dir, _ = self._scan()
        failed = ProduceResult(topic=KAFKA_PERSON)
        failed.set_result(KafkaError(-192, "Local: Message timed out"), None)
        actions_path = scan_dir / "republish.jsonl"
        republish = verbs.VERBS["republish"]

        def republish_then_sigterm(rows: list[dict], context: verbs.VerbContext) -> None:
            republish(rows, context)
            os.kill(os.getpid(), signal.SIGTERM)

        with (
            patch.object(ClickhouseProducer, "produce", return_value=failed),
            patch.dict(verbs.VERBS, {"republish": republish_then_sigterm}),
            pytest.raises(SystemExit),
        ):
            verbs.run_verb(scan_dir, "republish", apply=True, actions_path=actions_path)

        last = {a["key"]: a["outcome"] for a in map(json.loads, actions_path.read_text().splitlines())}
        assert last[key] == "undelivered"
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL

    def test_bury_paces_each_tombstone_call(self):
        for version in (2, 3):
            deleted = self._pg_person(version=version)
            tombstone_persons_in_postgres(self.team.pk, [deleted.uuid])
            self._ch_person(str(deleted.uuid), 7, {"email": "old@example.com"})
        scan_dir, _ = self._scan()

        with (
            patch.object(repairs, "_WRITE_BATCH_SIZE", 1),
            patch.object(repairs._WritePacer, "before_write", autospec=True) as before_write,
        ):
            outcomes = self._run(scan_dir, "bury", apply=True)

        assert [a["outcome"] for a in outcomes] == ["republished", "republished"]
        assert before_write.call_count == 2

    def test_merge_stale_sends_clickhouse_only_properties_then_republishes_once_ingestion_applied_them(self):
        stale = self._pg_person(version=1, distinct_ids=["s-1"])
        self._ch_person(str(stale.uuid), 40, {"email": "pg@example.com", "plan": "pro"})
        self._ch_mapping("s-1", str(stale.uuid), 0)
        scan_dir, before = self._scan()
        assert before == {str(stale.uuid): ("stale", "merge_stale")}

        with patch("posthog.models.person.divergence.stale_merge.capture_internal") as capture:
            first = self._run(scan_dir, "merge_stale", apply=True)

        assert [(a["key"], a["outcome"]) for a in first if a["kind"] == "person"] == [(str(stale.uuid), "merge_queued")]
        assert capture.call_args.kwargs["distinct_id"] == "s-1"
        assert capture.call_args.kwargs["properties"] == {"$set_once": {"plan": "pro"}}

        fake = get_active_fake()
        assert fake is not None
        stored = fake.stored_person(self.team.pk, str(stale.uuid))
        assert stored is not None
        stored.properties = json.dumps({"email": "pg@example.com", "plan": "pro"}).encode()
        with patch("posthog.models.person.divergence.stale_merge.capture_internal") as capture:
            second = self._run(scan_dir, "merge_stale", apply=True, resume=True)

        capture.assert_not_called()
        assert [(a["key"], a["outcome"]) for a in second[len(first) :] if a["kind"] == "person"] == [
            (str(stale.uuid), "repaired")
        ]
        assert self._scan()[1] == {}
