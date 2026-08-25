import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import requests

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team

from products.ai_observability.backend.instrumentation_checklist import fetch_checklist_stats, grade_checklist

# Every seeded event carries this trace-id prefix so --reset can find them again without
# touching AI events that arrived from a real SDK.
SEED_PREFIX = "checklist-seed-"

STAGES = ["reset", "sessions", "decline_sessions", "tools", "identity", "spans"]

# Above the grader's volume floor, so a freshly reset project grades warning rather than pending.
BASELINE_GENERATIONS = 25

INGESTION_POLL_SECONDS = 60


def _trace_id(stage: str, index: int) -> str:
    return f"{SEED_PREFIX}{stage}-{index}-{uuid.uuid4().hex[:8]}"


def _generation(trace_id: str, distinct_id: str, seconds_ago: int, **extra: Any) -> dict[str, Any]:
    return {
        "event": "$ai_generation",
        "distinct_id": distinct_id,
        "timestamp": (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat(),
        "properties": {
            "$ai_trace_id": trace_id,
            "$ai_model": "gpt-5-mini",
            "$ai_provider": "openai",
            "$ai_input": [{"role": "user", "content": "Tell me a fun fact about hedgehogs"}],
            "$ai_input_tokens": 10,
            "$ai_output_choices": [
                {"role": "assistant", "content": "Hedgehogs have around 5,000 to 7,000 spines on their backs!"}
            ],
            "$ai_output_tokens": 20,
            "$ai_latency": 1.5,
            **extra,
        },
    }


class Command(BaseCommand):
    help = "Seed AI events that walk a project through the instrumentation checklist, one check at a time."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team to seed events for.")
        parser.add_argument(
            "--stage",
            choices=STAGES,
            required=True,
            help=(
                "reset wipes previously seeded events and leaves every check warning. "
                "Each other stage adds the events one check is waiting for. "
                "decline_sessions is the alternative to sessions: it answers the same check by "
                "declaring the workload finishes in one trace."
            ),
        )
        parser.add_argument(
            "--capture-host",
            default="http://localhost:8010",
            help="Host serving the capture endpoint.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Seeding fabricated AI events into a real project would corrupt its checklist, its Sessions
        # and Tools tabs, and its billing counts.
        if not settings.DEBUG:
            raise CommandError("This command seeds fake AI events and only runs with DEBUG on.")

        team_id: int = options["team_id"]
        stage: str = options["stage"]
        self.capture_host: str = options["capture_host"].rstrip("/")

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"No team with id {team_id}.")

        self.team = team

        if stage == "reset":
            self._reset(team_id)
        else:
            getattr(self, f"_{stage}")()

        self._report(team)

    def _capture(self, events: list[dict[str, Any]]) -> None:
        """Send events the way a customer's SDK would, so ingestion shapes them like real data.

        Writing to ClickHouse directly skips the materialized view that moves heavy properties
        ($ai_input, $ai_output_choices, $ai_tools) out of the JSON blob into native columns, so
        seeded rows would read back differently from anything a real project sends.
        """
        before = self._seeded_count()

        for event in events:
            response = requests.post(
                f"{self.capture_host}/i/v0/e/",
                json={"api_key": self.team.api_token, **event},
                timeout=10,
            )
            if response.status_code != 200:
                raise CommandError(f"Capture rejected an event ({response.status_code}): {response.text}")

        self._await_ingestion(before, len(events))

    def _await_ingestion(self, before: int, expected: int) -> None:
        deadline = time.monotonic() + INGESTION_POLL_SECONDS
        while time.monotonic() < deadline:
            time.sleep(1)
            landed = self._seeded_count() - before
            if landed >= expected:
                return
        raise CommandError(
            f"Only {self._seeded_count() - before} of {expected} events reached ai_events within "
            f"{INGESTION_POLL_SECONDS}s. Is the ingestion stack running?"
        )

    def _seeded_count(self) -> int:
        rows = sync_execute(
            "SELECT count() FROM ai_events WHERE team_id = %(team_id)s AND trace_id LIKE %(prefix)s",
            {"team_id": self.team.pk, "prefix": f"{SEED_PREFIX}%"},
        )
        return int(rows[0][0])

    def _reset(self, team_id: int) -> None:
        for table in ("sharded_ai_events", "sharded_events"):
            sync_execute(
                f"ALTER TABLE {table} DELETE WHERE team_id = %(team_id)s "
                "AND JSONExtractString(properties, '$ai_trace_id') LIKE %(prefix)s",
                {"team_id": team_id, "prefix": f"{SEED_PREFIX}%"},
                settings={"mutations_sync": 1},
            )

        events = []
        for index in range(BASELINE_GENERATIONS):
            trace_id = _trace_id("bare", index)
            # A distinct_id equal to the trace id is what an unidentified SDK generation looks like,
            # so the identity check reads these as anonymous.
            events.append(_generation(trace_id, distinct_id=trace_id, seconds_ago=index + 1))
        self._capture(events)
        self.stdout.write(f"Reset and captured {len(events)} unadorned generations.")

    def _sessions(self) -> None:
        session_id = f"{SEED_PREFIX}conversation-{uuid.uuid4().hex[:6]}"
        events = []
        for turn in range(3):
            trace_id = _trace_id("session", turn)
            events.append(
                _generation(trace_id, distinct_id=trace_id, seconds_ago=turn + 1, **{"$ai_session_id": session_id})
            )
        self._capture(events)
        self.stdout.write(f"Captured {len(events)} generations sharing one $ai_session_id.")

    def _decline_sessions(self) -> None:
        events = []
        for index in range(3):
            trace_id = _trace_id("declined", index)
            events.append(
                _generation(trace_id, distinct_id=trace_id, seconds_ago=index + 1, **{"$ai_session_id": None})
            )
        self._capture(events)
        self.stdout.write(f"Captured {len(events)} generations declaring $ai_session_id as null.")

    def _tools(self) -> None:
        events = []
        for index in range(2):
            trace_id = _trace_id("tools", index)
            events.append(
                _generation(
                    trace_id,
                    distinct_id=trace_id,
                    seconds_ago=index + 1,
                    **{
                        "$ai_tools": [
                            {
                                "type": "function",
                                "function": {"name": "search_docs", "description": "Search the product docs"},
                            }
                        ],
                        "$ai_output_choices": [
                            {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "type": "function",
                                        "id": f"call_{index}",
                                        "function": {"name": "search_docs", "arguments": '{"query":"hedgehogs"}'},
                                    }
                                ],
                            }
                        ],
                    },
                )
            )
        self._capture(events)
        self.stdout.write(f"Captured {len(events)} generations that declare and call a tool.")

    def _identity(self) -> None:
        events = [
            _generation(_trace_id("identity", index), distinct_id=f"person-{index}@example.com", seconds_ago=index + 1)
            for index in range(3)
        ]
        self._capture(events)
        self.stdout.write(f"Captured {len(events)} generations attributed to real distinct IDs.")

    def _spans(self) -> None:
        events = []
        for index in range(2):
            trace_id = _trace_id("spans", index)
            events.append(_generation(trace_id, distinct_id=trace_id, seconds_ago=index + 1))
            events.append(
                {
                    "event": "$ai_span",
                    "distinct_id": trace_id,
                    "timestamp": (datetime.now(UTC) - timedelta(seconds=index + 1)).isoformat(),
                    "properties": {
                        "$ai_trace_id": trace_id,
                        "$ai_parent_id": trace_id,
                        "$ai_span_name": "retrieve_documents",
                        "$ai_latency": 0.2,
                    },
                }
            )
        self._capture(events)
        self.stdout.write(f"Captured {len(events)} events including spans nested under their trace.")

    def _report(self, team: Team) -> None:
        stats = fetch_checklist_stats(team)
        self.stdout.write("")
        self.stdout.write(f"{'check':>16}  {'status':<9} counts")
        self.stdout.write("-" * 72)
        for check in grade_checklist(stats, ()):
            counts = "  ".join(f"{name}={value}" for name, value in check.stats.items())
            self.stdout.write(f"{check.key.value:>16}  {check.status.value:<9} {counts}")
        self.stdout.write("")
