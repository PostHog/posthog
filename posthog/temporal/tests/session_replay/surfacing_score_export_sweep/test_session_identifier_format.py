"""Parity with the mirror's shared session identifier fixture."""

import json
from pathlib import Path

from parameterized import parameterized

from posthog.temporal.session_replay.surfacing_score_export_sweep.session_identifier_format import (
    RAW_SESSION_IDENTIFIERS_START_MS,
    session_start_timestamp_from_uuid_v7,
    uses_raw_session_identifiers,
)

_CASES_PATH = (
    Path(__file__).parents[5]
    / "nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format-cases.json"
)
_FIXTURE = json.loads(_CASES_PATH.read_text())


class TestUsesRawSessionIdentifiers:
    def test_cutoff_matches_the_mirror_fixture(self) -> None:
        assert RAW_SESSION_IDENTIFIERS_START_MS == _FIXTURE["cutoffMs"]

    @parameterized.expand([(case["sessionId"], case["rawIdentifiers"]) for case in _FIXTURE["cases"]])
    def test_matches_the_mirror(self, session_id: str, raw_identifiers: bool) -> None:
        assert uses_raw_session_identifiers(session_id) is raw_identifiers

    def test_reads_the_embedded_millisecond_timestamp(self) -> None:
        assert session_start_timestamp_from_uuid_v7("01a0a4f0-3200-7000-8000-000000000001") == (
            RAW_SESSION_IDENTIFIERS_START_MS
        )
        assert session_start_timestamp_from_uuid_v7("not-a-uuid") is None
