import json
import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from posthog.models import Team

from ...logic.effectiveness import TeamEffectiveness, TeamSkipped, capture_effectiveness, measure_team, trace_url
from ...temporal.usage_scan.types import DEFAULT_TELEMETRY_TEAM_ID


def _no_heartbeat() -> None:
    return None


def _report(result: TeamEffectiveness) -> dict[str, object]:
    return {
        "team_id": result.team_id,
        "window": [result.window_start.isoformat(), result.window_end.isoformat()],
        "sessions_read": result.sessions_read,
        "is_sample": result.is_sample,
        "unread_sessions": result.unread_sessions,
        "analysis_sessions": result.analysis_sessions,
        "unchecked_queries": result.unchecked_queries,
        "unchecked_sessions": result.unchecked_sessions,
        "served_share": result.served_share,
        "capture_share": result.capture_share,
        "headline_sessions": {outcome.value: count for outcome, count in result.headline_counts.most_common()},
        "metric_pairs": {outcome.value: count for outcome, count in result.metric_pair_counts.most_common()},
        "examples": [
            {
                "outcome": row.outcome.value,
                "metric": row.metric_name,
                "relation": row.relation.value if row.relation else None,
                "missed_reason": row.missed_reason.value if row.missed_reason else None,
                "question": row.question,
                "judge_reasoning": row.reasoning,
                "trace": trace_url(row.session_id, result.telemetry_team_id),
            }
            for row in result.rows
            if row.is_example
        ],
    }


class Command(BaseCommand):
    help = "Measure one team's catalog effectiveness and print it. Nothing is captured without --capture."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team to measure.")
        parser.add_argument("--start", help="Window start, as an ISO date. The default is 7 days ago.")
        parser.add_argument("--end", help="Window end, as an ISO date. The default is now.")
        parser.add_argument("--telemetry-team-id", type=int, default=DEFAULT_TELEMETRY_TEAM_ID)
        parser.add_argument("--capture", action="store_true", help="Send the outcome events.")
        parser.add_argument("--rows-file", type=Path, help="Write one JSON line per session and asset to this file.")

    def handle(
        self,
        *args: object,
        team_id: int,
        start: str | None,
        end: str | None,
        telemetry_team_id: int,
        capture: bool,
        rows_file: Path | None,
        **options: object,
    ) -> None:
        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise CommandError(f"Team {team_id} does not exist.")
        window_end = _parse(end) if end else timezone.now()
        window_start = _parse(start) if start else window_end - timedelta(days=7)
        result = asyncio.run(
            measure_team(
                team_id=team_id,
                telemetry_team_id=telemetry_team_id,
                window_start=window_start,
                window_end=window_end,
                heartbeat=_no_heartbeat,
            )
        )
        if isinstance(result, TeamSkipped):
            raise CommandError(f"Skipped team {team_id}: {result.reason}.")
        if capture:
            capture_effectiveness(result, team)
        if rows_file:
            rows_file.write_text(
                "".join(json.dumps(dataclasses.asdict(row), default=str) + "\n" for row in result.rows)
            )
        self.stdout.write(json.dumps(_report(result), indent=2))


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
