from textwrap import dedent
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.sync import database_sync_to_async

from ee.hogai.tool import MaxTool

logger = structlog.get_logger(__name__)


# Verdict labels match the verdict ladder in
# products/replay/skills/diagnosing-missing-recordings/references/diagnosis-logic.md
VERDICT_CAPTURED = "captured"
VERDICT_AD_BLOCKED = "ad_blocked"
VERDICT_DISABLED = "disabled"
VERDICT_TRIGGER_PENDING = "trigger_pending"
VERDICT_SAMPLED_OUT = "sampled_out"
VERDICT_BUFFERING_EMPTY = "buffering_empty"
VERDICT_PAUSED = "paused"
VERDICT_FLUSH_BLOCKED = "flush_blocked"
VERDICT_NO_EVENTS = "no_events"
VERDICT_DISABLED_PROJECT = "disabled_project"
VERDICT_UNKNOWN = "unknown"


VERDICT_DESCRIPTIONS: dict[str, str] = {
    VERDICT_CAPTURED: (
        "The SDK captured a recording for this session — if the user can't find it, the issue is likely "
        "downstream (still processing, filtered out by duration/activity thresholds, or deleted by retention)."
    ),
    VERDICT_AD_BLOCKED: (
        "The rrweb recorder script failed to load (`$sdk_debug_recording_script_not_loaded` was true). "
        "Most commonly this is caused by a browser ad blocker, corporate CSP, or network-level blocking. "
        "Recommend testing without the ad blocker, or routing the recorder script through a proxy/custom domain."
    ),
    VERDICT_DISABLED: (
        "The SDK reported `$recording_status = 'disabled'`. Replay is turned off for this session — "
        "either via project settings (Settings > Session replay), the SDK init config "
        "(`session_recording: { enabled: false }`), or a runtime call like "
        "`posthog.set_config({ disable_session_recording: true })`."
    ),
    VERDICT_TRIGGER_PENDING: (
        "Recording was gated on a trigger (URL pattern, event, or linked feature flag) that never matched "
        "during this session. Review the trigger configuration in Settings > Session replay to ensure it "
        "covers the pages/events the user actually visits."
    ),
    VERDICT_SAMPLED_OUT: (
        "The SDK reported `$session_recording_start_reason = 'sampled_out'`. The session was randomly "
        "excluded by the configured sample rate. To capture more sessions, raise the sample rate in "
        "project settings or use a trigger to guarantee capture for important flows."
    ),
    VERDICT_BUFFERING_EMPTY: (
        "The SDK initialized in buffering mode but never produced snapshots — the buffer length stayed at 0. "
        "Common causes: very short session, page navigated away before the first snapshot, or the configured "
        "minimum duration threshold was not met."
    ),
    VERDICT_PAUSED: (
        "Recording is paused for this session (`$recording_status = 'paused'`). Typical causes: a "
        "consent mechanism is awaiting user opt-in, `posthog.session_recording.pause()` was called, "
        "or the session exceeded a configured maximum duration."
    ),
    VERDICT_FLUSH_BLOCKED: (
        "The SDK is producing snapshots (buffer length keeps climbing) but nothing is reaching PostHog "
        "(flushed_size stays at 0). Most commonly an ad blocker is silently blocking `POST /s/`, or a "
        "reverse proxy isn't forwarding `/s/` to the capture service. Different from AD_BLOCKED — the "
        "rrweb script loaded fine, but the upload is being blocked."
    ),
    VERDICT_NO_EVENTS: (
        "No events were found for this session ID in the recent event window. If this is a real session, "
        "either the SDK never sent any events (e.g., capture disabled, network blocked, distinct ID mismatch), "
        "or the session ID is invalid."
    ),
    VERDICT_DISABLED_PROJECT: (
        "Session replay is disabled at the project level (`session_recording_opt_in = false`). No "
        "sessions will be recorded until replay is enabled in Settings > Session replay."
    ),
    VERDICT_UNKNOWN: (
        "The available diagnostic signals don't match a known failure pattern. The SDK may be too old to "
        "emit the diagnostic properties this tool relies on. Direct the user to "
        "https://posthog.com/docs/session-replay/troubleshooting for manual investigation."
    ),
}


def _classify_signals(row: dict[str, Any]) -> str:
    """Apply the verdict ladder from diagnosing-missing-recordings/references/diagnosis-logic.md."""
    has_recording = row.get("has_recording")
    if has_recording is True or has_recording == "true":
        return VERDICT_CAPTURED

    script_not_loaded = row.get("script_not_loaded")
    if script_not_loaded is True or script_not_loaded == "true":
        return VERDICT_AD_BLOCKED

    recording_status = row.get("recording_status")
    if recording_status == "disabled":
        return VERDICT_DISABLED

    trigger_statuses = [
        row.get("url_trigger"),
        row.get("event_trigger"),
        row.get("flag_trigger"),
    ]
    has_pending = any(s == "trigger_pending" for s in trigger_statuses)
    has_matched = any(s == "trigger_matched" for s in trigger_statuses)
    if has_pending and not has_matched:
        return VERDICT_TRIGGER_PENDING

    if row.get("start_reason") == "sampled_out":
        return VERDICT_SAMPLED_OUT

    buffer_length = row.get("buffer_length") or 0
    flushed_size = row.get("flushed_size") or 0
    max_buffer_length = row.get("max_buffer_length") or 0
    max_flushed_size = row.get("max_flushed_size") or 0

    if recording_status == "buffering" and buffer_length == 0 and flushed_size == 0:
        return VERDICT_BUFFERING_EMPTY

    if recording_status == "sampled" or (recording_status == "active" and max_flushed_size > 0):
        return VERDICT_CAPTURED

    if recording_status == "paused":
        return VERDICT_PAUSED

    if max_buffer_length > 0 and max_flushed_size == 0:
        return VERDICT_FLUSH_BLOCKED

    return VERDICT_UNKNOWN


class DiagnoseMissingRecordingsToolArgs(BaseModel):
    session_id: str | None = Field(
        default=None,
        description=dedent(
            """
            Optional session ID (`$session_id`) to diagnose. If provided, the tool inspects diagnostic
            signals attached to events for that specific session. If omitted, the tool inspects recent
            events across the project to detect fleet-wide patterns (sample rate too low, recording
            disabled, scripts blocked, etc.).
            """
        ).strip(),
    )


DIAGNOSE_MISSING_RECORDINGS_DESCRIPTION = dedent(
    """
    Diagnose why one or more session recordings are missing or weren't captured.

    Use this tool whenever the user reports problems with replay capture, such as:
    - "my session replays are broken / aren't working"
    - "why isn't this session recorded?"
    - "we used to have replays but they've stopped showing up"
    - "no recordings appear in the playlist"
    - any complaint about missing, broken, or unexpectedly empty replays.

    The tool queries the SDK diagnostic properties (`$has_recording`, `$recording_status`,
    `$session_recording_start_reason`, `$sdk_debug_recording_script_not_loaded`, trigger
    statuses, sample rate, internal buffer length, flushed size) emitted on every event
    and applies the verdict ladder documented in the `diagnosing-missing-recordings` skill:
    captured -> ad_blocked -> disabled -> trigger_pending -> sampled_out ->
    buffering_empty -> paused -> flush_blocked -> unknown.

    It also reports the project-level replay configuration (opt-in flag, sample rate,
    minimum duration, configured triggers) so you can spot project-wide misconfigurations.

    Prefer this tool over `filter_session_recordings` when the user is asking *why* a
    recording is missing rather than asking to find recordings.
    """
).strip()


class DiagnoseMissingRecordingsTool(MaxTool):
    name: Literal["diagnose_missing_recordings"] = "diagnose_missing_recordings"
    description: str = DIAGNOSE_MISSING_RECORDINGS_DESCRIPTION
    args_schema: type[BaseModel] = DiagnoseMissingRecordingsToolArgs

    def get_required_resource_access(self):
        return [("session_recording", "viewer")]

    async def _arun_impl(self, session_id: str | None = None) -> tuple[str, dict[str, Any] | None]:
        team_settings = await database_sync_to_async(self._collect_team_settings, thread_sensitive=False)()

        try:
            if session_id:
                session_signals = await self._query_session_signals(session_id)
            else:
                session_signals = await self._query_recent_signals()
        except Exception as e:
            logger.exception(
                "diagnose_missing_recordings query failed",
                team_id=self._team.pk,
                session_id=session_id,
            )
            return (
                f"Could not query diagnostic signals from events: {e}. "
                "This may indicate the project has no recent events, or the events table is unreachable. "
                "Recommend checking https://posthog.com/docs/session-replay/troubleshooting.",
                None,
            )

        verdicts = self._verdicts_from_signals(session_signals, team_settings)
        formatted = self._format_report(
            session_id=session_id,
            team_settings=team_settings,
            session_signals=session_signals,
            verdicts=verdicts,
        )
        artifact: dict[str, Any] = {
            "session_id": session_id,
            "team_settings": team_settings,
            "verdicts": verdicts,
            "signal_rows": session_signals,
        }
        return formatted, artifact

    def _collect_team_settings(self) -> dict[str, Any]:
        team = self._team
        sample_rate_raw = team.session_recording_sample_rate
        sample_rate = float(sample_rate_raw) if sample_rate_raw is not None else None
        url_triggers = list(team.session_recording_url_trigger_config or [])
        event_triggers = list(team.session_recording_event_trigger_config or [])
        return {
            "session_recording_opt_in": bool(team.session_recording_opt_in),
            "session_recording_sample_rate": sample_rate,
            "session_recording_minimum_duration_milliseconds": team.session_recording_minimum_duration_milliseconds,
            "session_recording_linked_flag": team.session_recording_linked_flag,
            "session_recording_url_trigger_count": len(url_triggers),
            "session_recording_event_trigger_count": len(event_triggers),
            "session_recording_trigger_match_type_config": team.session_recording_trigger_match_type_config,
        }

    async def _query_session_signals(self, session_id: str) -> list[dict[str, Any]]:
        # Aggregate across all events for this session so we can detect FLUSH_BLOCKED
        # (buffer climbs across events while flushed_size stays at 0).
        query = """
            SELECT
                anyLast(properties.$has_recording) AS has_recording,
                anyLast(properties.$recording_status) AS recording_status,
                anyLast(properties.$session_recording_start_reason) AS start_reason,
                anyLast(properties.$sdk_debug_recording_script_not_loaded) AS script_not_loaded,
                anyLast(properties.$sdk_debug_replay_url_trigger_status) AS url_trigger,
                anyLast(properties.$sdk_debug_replay_event_trigger_status) AS event_trigger,
                anyLast(properties.$sdk_debug_replay_linked_flag_trigger_status) AS flag_trigger,
                anyLast(properties.$replay_sample_rate) AS sample_rate,
                anyLast(properties.$sdk_debug_replay_internal_buffer_length) AS buffer_length,
                anyLast(properties.$sdk_debug_replay_flushed_size) AS flushed_size,
                max(toFloat64OrNull(toString(properties.$sdk_debug_replay_internal_buffer_length))) AS max_buffer_length,
                max(toFloat64OrNull(toString(properties.$sdk_debug_replay_flushed_size))) AS max_flushed_size,
                anyLast(properties.$lib) AS sdk_library,
                anyLast(properties.$lib_version) AS sdk_version,
                count() AS event_count
            FROM events
            WHERE $session_id = {session_id}
                AND timestamp > now() - INTERVAL 14 DAY
        """
        rows = await self._run_hogql(
            query=query,
            placeholders={"session_id": ast.Constant(value=session_id)},
        )
        return self._rows_to_dicts(rows)

    async def _query_recent_signals(self) -> list[dict[str, Any]]:
        # When no session_id is given we look at the most recent sessions to infer fleet-wide patterns.
        query = """
            SELECT
                anyLast(properties.$has_recording) AS has_recording,
                anyLast(properties.$recording_status) AS recording_status,
                anyLast(properties.$session_recording_start_reason) AS start_reason,
                anyLast(properties.$sdk_debug_recording_script_not_loaded) AS script_not_loaded,
                anyLast(properties.$sdk_debug_replay_url_trigger_status) AS url_trigger,
                anyLast(properties.$sdk_debug_replay_event_trigger_status) AS event_trigger,
                anyLast(properties.$sdk_debug_replay_linked_flag_trigger_status) AS flag_trigger,
                anyLast(properties.$replay_sample_rate) AS sample_rate,
                anyLast(properties.$sdk_debug_replay_internal_buffer_length) AS buffer_length,
                anyLast(properties.$sdk_debug_replay_flushed_size) AS flushed_size,
                max(toFloat64OrNull(toString(properties.$sdk_debug_replay_internal_buffer_length))) AS max_buffer_length,
                max(toFloat64OrNull(toString(properties.$sdk_debug_replay_flushed_size))) AS max_flushed_size,
                anyLast(properties.$lib) AS sdk_library,
                anyLast(properties.$lib_version) AS sdk_version,
                count() AS event_count
            FROM events
            WHERE timestamp > now() - INTERVAL 1 DAY
                AND notEmpty(toString($session_id))
            GROUP BY $session_id
            ORDER BY max(timestamp) DESC
            LIMIT 20
        """
        rows = await self._run_hogql(query=query, placeholders={})
        return self._rows_to_dicts(rows)

    async def _run_hogql(self, *, query: str, placeholders: dict[str, ast.Expr]) -> list[tuple]:
        @database_sync_to_async(thread_sensitive=False)
        def _execute() -> list[tuple]:
            with tags_context(
                product=Product.MAX_AI,
                feature=Feature.POSTHOG_AI,
                team_id=self._team.pk,
                org_id=self._team.organization_id,
            ):
                response = execute_hogql_query(
                    query_type="DiagnoseMissingRecordingsTool",
                    query=query,
                    team=self._team,
                    placeholders=placeholders,
                )
            return list(response.results or [])

        return await _execute()

    @staticmethod
    def _rows_to_dicts(rows: list[tuple]) -> list[dict[str, Any]]:
        keys = [
            "has_recording",
            "recording_status",
            "start_reason",
            "script_not_loaded",
            "url_trigger",
            "event_trigger",
            "flag_trigger",
            "sample_rate",
            "buffer_length",
            "flushed_size",
            "max_buffer_length",
            "max_flushed_size",
            "sdk_library",
            "sdk_version",
            "event_count",
        ]
        return [dict(zip(keys, row)) for row in rows]

    def _verdicts_from_signals(
        self,
        rows: list[dict[str, Any]],
        team_settings: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not team_settings.get("session_recording_opt_in"):
            return [
                {
                    "verdict": VERDICT_DISABLED_PROJECT,
                    "description": VERDICT_DESCRIPTIONS[VERDICT_DISABLED_PROJECT],
                    "row_count": len(rows),
                }
            ]

        if not rows or all((r.get("event_count") or 0) == 0 for r in rows):
            return [
                {
                    "verdict": VERDICT_NO_EVENTS,
                    "description": VERDICT_DESCRIPTIONS[VERDICT_NO_EVENTS],
                    "row_count": 0,
                }
            ]

        counts: dict[str, int] = {}
        for row in rows:
            verdict = _classify_signals(row)
            counts[verdict] = counts.get(verdict, 0) + 1

        return [
            {
                "verdict": verdict,
                "description": VERDICT_DESCRIPTIONS.get(verdict, ""),
                "row_count": count,
            }
            for verdict, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        ]

    def _format_report(
        self,
        *,
        session_id: str | None,
        team_settings: dict[str, Any],
        session_signals: list[dict[str, Any]],
        verdicts: list[dict[str, Any]],
    ) -> str:
        lines: list[str] = []
        if session_id:
            lines.append(f"Diagnosis for session `{session_id}`:")
        else:
            lines.append("Project-wide replay diagnosis (last 24h, up to 20 most recent sessions):")

        lines.append("")
        lines.append("**Project replay settings:**")
        lines.append(f"- Replay enabled: {team_settings['session_recording_opt_in']}")
        sample_rate = team_settings["session_recording_sample_rate"]
        lines.append(f"- Sample rate: {sample_rate if sample_rate is not None else '1.0 (default, all sessions)'}")
        min_duration = team_settings["session_recording_minimum_duration_milliseconds"]
        lines.append(f"- Minimum duration (ms): {min_duration if min_duration is not None else 'not set'}")
        lines.append(f"- URL triggers configured: {team_settings['session_recording_url_trigger_count']}")
        lines.append(f"- Event triggers configured: {team_settings['session_recording_event_trigger_count']}")
        if team_settings["session_recording_linked_flag"]:
            lines.append(f"- Linked feature flag: {team_settings['session_recording_linked_flag']}")

        lines.append("")
        lines.append("**Verdict(s):**")
        for v in verdicts:
            row_suffix = f" ({v['row_count']} session(s))" if not session_id else ""
            lines.append(f"- `{v['verdict']}`{row_suffix} — {v['description']}")

        if session_signals:
            lines.append("")
            lines.append("**Diagnostic signals seen:**")
            for row in session_signals[:5]:
                signal_parts: list[str] = []
                for key in (
                    "recording_status",
                    "start_reason",
                    "script_not_loaded",
                    "url_trigger",
                    "event_trigger",
                    "flag_trigger",
                    "sample_rate",
                    "max_buffer_length",
                    "max_flushed_size",
                    "sdk_library",
                    "sdk_version",
                ):
                    val = row.get(key)
                    if val not in (None, ""):
                        signal_parts.append(f"{key}={val}")
                if signal_parts:
                    lines.append(f"- {', '.join(signal_parts)}")

        lines.append("")
        lines.append(
            "Reference: products/replay/skills/diagnosing-missing-recordings/SKILL.md and "
            "https://posthog.com/docs/session-replay/troubleshooting"
        )
        return "\n".join(lines)
