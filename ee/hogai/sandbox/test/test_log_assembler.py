import json
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.backend.models import Task, TaskRun

from ee.hogai.sandbox.log_assembler import LOG_ENTRIES_MAX_LIMIT, assemble_conversation_log


def _entry(seq: int, ts: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": "notification", "seq": seq}
    if ts is not None:
        entry["timestamp"] = ts
    return entry


def _ndjson(entries: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e) for e in entries)


class TestLogAssembler(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Sandbox",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _make_run(self, status: str = TaskRun.Status.COMPLETED) -> TaskRun:
        return TaskRun.objects.create(task=self.task, team=self.team, status=status)

    def test_no_runs_returns_empty(self) -> None:
        result = assemble_conversation_log([])
        self.assertEqual(result["entries"], [])
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["current_run_status"])

    def test_concatenates_runs_in_order(self) -> None:
        run1 = self._make_run()
        run2 = self._make_run(status=TaskRun.Status.IN_PROGRESS)
        contents = {
            run1.log_url: _ndjson([_entry(1), _entry(2)]),
            run2.log_url: _ndjson([_entry(3), _entry(4)]),
        }
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            side_effect=lambda url, missing_ok=True: contents.get(url, ""),
        ):
            result = assemble_conversation_log([run1, run2])

        self.assertEqual([e["seq"] for e in result["entries"]], [1, 2, 3, 4])
        self.assertFalse(result["has_more"])
        # current_run_status is the last (most recent) run's status
        self.assertEqual(result["current_run_status"], TaskRun.Status.IN_PROGRESS)

    def test_desc_order_reverses(self) -> None:
        run = self._make_run()
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            return_value=_ndjson([_entry(1), _entry(2), _entry(3)]),
        ):
            result = assemble_conversation_log([run], order="desc")
        self.assertEqual([e["seq"] for e in result["entries"]], [3, 2, 1])

    def test_limit_caps_and_sets_has_more(self) -> None:
        run = self._make_run()
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            return_value=_ndjson([_entry(i) for i in range(5)]),
        ):
            result = assemble_conversation_log([run], limit=2)
        self.assertEqual([e["seq"] for e in result["entries"]], [0, 1])
        self.assertTrue(result["has_more"])

    def test_limit_exactly_matches_no_has_more(self) -> None:
        run = self._make_run()
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            return_value=_ndjson([_entry(0), _entry(1)]),
        ):
            result = assemble_conversation_log([run], limit=2)
        self.assertEqual(len(result["entries"]), 2)
        self.assertFalse(result["has_more"])

    @parameterized.expand([(0, LOG_ENTRIES_MAX_LIMIT), (LOG_ENTRIES_MAX_LIMIT + 100, LOG_ENTRIES_MAX_LIMIT), (1, 1)])
    def test_limit_is_clamped(self, requested: int, expected_cap: int) -> None:
        run = self._make_run()
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            return_value=_ndjson([_entry(i) for i in range(3)]),
        ):
            result = assemble_conversation_log([run], limit=requested)
        self.assertLessEqual(len(result["entries"]), expected_cap)

    def test_after_filters_entries(self) -> None:
        run = self._make_run()
        entries = [
            _entry(1, "2024-01-01T00:00:00Z"),
            _entry(2, "2024-01-02T00:00:00Z"),
            _entry(3, "2024-01-03T00:00:00Z"),
        ]
        after = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            return_value=_ndjson(entries),
        ):
            result = assemble_conversation_log([run], after=after)
        self.assertEqual([e["seq"] for e in result["entries"]], [2, 3])

    def test_after_drops_entries_without_timestamp(self) -> None:
        run = self._make_run()
        entries = [_entry(1), _entry(2, "2024-06-01T00:00:00Z")]
        after = datetime(2024, 1, 1, tzinfo=UTC)
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            return_value=_ndjson(entries),
        ):
            result = assemble_conversation_log([run], after=after)
        self.assertEqual([e["seq"] for e in result["entries"]], [2])

    def test_malformed_lines_skipped(self) -> None:
        run = self._make_run()
        raw = "\n".join([json.dumps(_entry(1)), "{not json", "", "  ", json.dumps(_entry(2))])
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            return_value=raw,
        ):
            result = assemble_conversation_log([run])
        self.assertEqual([e["seq"] for e in result["entries"]], [1, 2])

    def test_non_dict_lines_skipped(self) -> None:
        run = self._make_run()
        raw = "\n".join([json.dumps(_entry(1)), json.dumps([1, 2, 3]), json.dumps("a string")])
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            return_value=raw,
        ):
            result = assemble_conversation_log([run])
        self.assertEqual([e["seq"] for e in result["entries"]], [1])

    @parameterized.expand([(None,), ("",), ("   ",)])
    def test_empty_or_missing_log_yields_no_entries(self, content: str | None) -> None:
        run = self._make_run()
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            return_value=content,
        ):
            result = assemble_conversation_log([run])
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["current_run_status"], TaskRun.Status.COMPLETED)

    def test_has_more_across_runs(self) -> None:
        run1 = self._make_run()
        run2 = self._make_run(status=TaskRun.Status.FAILED)
        contents = {
            run1.log_url: _ndjson([_entry(1), _entry(2)]),
            run2.log_url: _ndjson([_entry(3), _entry(4)]),
        }
        with patch(
            "ee.hogai.sandbox.log_assembler.object_storage.read",
            side_effect=lambda url, missing_ok=True: contents.get(url, ""),
        ):
            result = assemble_conversation_log([run1, run2], limit=3)
        self.assertEqual([e["seq"] for e in result["entries"]], [1, 2, 3])
        self.assertTrue(result["has_more"])
        self.assertEqual(result["current_run_status"], TaskRun.Status.FAILED)
