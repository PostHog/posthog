import re
import json
import random
import hashlib

from django.test import SimpleTestCase

from products.ai_observability.backend.sample_traces import SAMPLE_TRACES_DIR, SampleEvent, SampleTraces, remap_ids

AGENTS_HINT = "Sample trace fixtures are generated; see products/ai_observability/fixtures/sample_traces/AGENTS.md."


def canonical_sha(obj: object) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class TestSampleTraceFixtures(SimpleTestCase):
    def test_generated_files_match_checksums(self) -> None:
        checksums = json.loads((SAMPLE_TRACES_DIR / "checksums.json").read_text())
        units = {p.stem: canonical_sha(json.loads(p.read_text())) for p in (SAMPLE_TRACES_DIR / "units").glob("*.json")}
        media = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (SAMPLE_TRACES_DIR / "media").iterdir()}
        sets = canonical_sha(json.loads((SAMPLE_TRACES_DIR / "sets.json").read_text()))

        mismatched = [
            f"{kind}/{name}"
            for kind, actual, expected in (("units", units, checksums["units"]), ("media", media, checksums["media"]))
            for name in sorted(actual.keys() | expected.keys())
            if actual.get(name) != expected.get(name)
        ]
        if sets != checksums["sets"]:
            mismatched.append("sets.json")

        self.assertEqual(mismatched, [], AGENTS_HINT)

    def test_units_reference_existing_units_and_media(self) -> None:
        unit_ids = {p.stem for p in (SAMPLE_TRACES_DIR / "units").glob("*.json")}
        media = {p.name for p in (SAMPLE_TRACES_DIR / "media").iterdir()}
        sets = json.loads((SAMPLE_TRACES_DIR / "sets.json").read_text())
        referenced_units = {uid for name, members in sets.items() if not name.startswith("_") for uid in members}
        text = "".join(p.read_text() for p in (SAMPLE_TRACES_DIR / "units").glob("*.json"))
        referenced_media = set(re.findall(r"⟦media:([^⟧]+)⟧", text)) | set(
            re.findall(r"https://media\.example\.com/([^\"\s]+)", text)
        )

        self.assertEqual(referenced_units - unit_ids, set())
        self.assertEqual(referenced_media - media, set())

    def test_only_selection_ignores_blank_entries(self) -> None:
        samples = SampleTraces()

        self.assertEqual(samples.unit_ids(only=["claude_code_plugin_session", " "]), ["claude_code_plugin_session"])
        with self.assertRaises(ValueError):
            samples.unit_ids(only=["", " "])


class TestRemapIds(SimpleTestCase):
    def test_remap_keeps_trace_span_session_and_evaluation_links(self) -> None:
        trace_id, span_id, session_id, generation_uuid = (
            "0198a7c2-0000-7000-8000-000000000001",
            "5543ef630ba66283",
            "conv-42",
            "0198a7c2-0000-7000-8000-000000000002",
        )
        events: list[SampleEvent] = [
            {
                "event": "$ai_trace",
                "offset_ms": 0,
                "distinct_id": "user-1",
                "properties": {"$ai_trace_id": trace_id, "$ai_session_id": session_id},
            },
            {
                "event": "$ai_span",
                "offset_ms": 5,
                "distinct_id": "user-1",
                "properties": {
                    "$ai_trace_id": trace_id,
                    "$ai_span_id": span_id,
                    "$ai_parent_id": trace_id,
                    "$ai_session_id": session_id,
                },
            },
            {
                "event": "$ai_generation",
                "uuid": generation_uuid,
                "offset_ms": 9,
                "distinct_id": "user-1",
                "properties": {
                    "$ai_trace_id": trace_id,
                    "$ai_parent_id": span_id,
                    "$ai_input": [{"role": "user", "content": f"see {trace_id}"}],
                },
            },
            {
                "event": "$ai_evaluation",
                "offset_ms": 12,
                "distinct_id": "user-1",
                "properties": {"$ai_trace_id": trace_id, "$ai_target_event_id": generation_uuid},
            },
        ]

        remapped = remap_ids(events, random.Random(7))
        trace, span, generation, evaluation = (e["properties"] for e in remapped)

        self.assertNotEqual(trace["$ai_trace_id"], trace_id)
        self.assertNotEqual(span["$ai_span_id"], span_id)
        self.assertNotEqual(trace["$ai_session_id"], session_id)
        self.assertEqual(
            {span["$ai_trace_id"], generation["$ai_trace_id"], span["$ai_parent_id"]}, {trace["$ai_trace_id"]}
        )
        self.assertEqual(generation["$ai_parent_id"], span["$ai_span_id"])
        self.assertEqual(span["$ai_session_id"], trace["$ai_session_id"])
        self.assertEqual(generation["$ai_input"], [{"role": "user", "content": f"see {trace['$ai_trace_id']}"}])
        self.assertNotEqual(remapped[2].get("uuid"), generation_uuid)
        self.assertEqual(evaluation["$ai_target_event_id"], remapped[2].get("uuid"))
