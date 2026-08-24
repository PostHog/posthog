import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client import sync_execute
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.team import Team

from products.ai_observability.backend.instrumentation_checklist import fetch_checklist_stats, grade_checklist

# Every seeded event carries this trace-id prefix so --reset can find them again without
# touching AI events that arrived from a real SDK.
SEED_PREFIX = "checklist-seed-"

STAGES = ["reset", "sessions", "tools", "identity", "spans"]

# Above the grader's volume floor, so a freshly reset project grades warning rather than pending.
BASELINE_GENERATIONS = 25


def _trace_id(stage: str, index: int) -> str:
    return f"{SEED_PREFIX}{stage}-{index}-{uuid.uuid4().hex[:8]}"


def _generation(team_id: int, trace_id: str, distinct_id: str, minutes_ago: int, **extra: Any) -> dict[str, Any]:
    return {
        "event": "$ai_generation",
        "team_id": team_id,
        "distinct_id": distinct_id,
        "timestamp": datetime.now(UTC) - timedelta(minutes=minutes_ago),
        "properties": {"$ai_trace_id": trace_id, "$ai_model": "gpt-5-mini", "$ai_provider": "openai", **extra},
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
                "Each other stage adds the events one check is waiting for."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Bulk-inserting fabricated AI events would corrupt a real project's checklist, its Sessions
        # and Tools tabs, and its billing counts.
        if not settings.DEBUG:
            raise CommandError("This command seeds fake AI events and only runs with DEBUG on.")

        team_id: int = options["team_id"]
        stage: str = options["stage"]

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"No team with id {team_id}.")

        if stage == "reset":
            self._reset(team_id)
        else:
            getattr(self, f"_{stage}")(team_id)

        self._report(team)

    def _reset(self, team_id: int) -> None:
        sync_execute(
            "ALTER TABLE sharded_ai_events DELETE WHERE team_id = %(team_id)s AND trace_id LIKE %(prefix)s",
            {"team_id": team_id, "prefix": f"{SEED_PREFIX}%"},
            settings={"mutations_sync": 1},
        )
        events = []
        for index in range(BASELINE_GENERATIONS):
            trace_id = _trace_id("bare", index)
            # distinct_id equal to the trace id is what an unidentified SDK generation looks like,
            # so the identity check reads these as anonymous.
            events.append(_generation(team_id, trace_id, distinct_id=trace_id, minutes_ago=index + 1))
        bulk_create_ai_events(events)
        self.stdout.write(f"Reset and seeded {len(events)} unadorned generations.")

    def _sessions(self, team_id: int) -> None:
        session_id = f"{SEED_PREFIX}conversation-{uuid.uuid4().hex[:6]}"
        events = []
        for turn in range(3):
            trace_id = _trace_id("session", turn)
            events.append(
                _generation(
                    team_id,
                    trace_id,
                    distinct_id=trace_id,
                    minutes_ago=turn + 1,
                    **{"$ai_session_id": session_id},
                )
            )
        bulk_create_ai_events(events)
        self.stdout.write(f"Added {len(events)} generations sharing one $ai_session_id.")

    def _tools(self, team_id: int) -> None:
        events = []
        for index in range(2):
            trace_id = _trace_id("tools", index)
            events.append(
                _generation(
                    team_id,
                    trace_id,
                    distinct_id=trace_id,
                    minutes_ago=index + 1,
                    **{
                        "$ai_tools": [{"type": "function", "function": {"name": "search_docs"}}],
                        "$ai_tools_called": ["search_docs"],
                    },
                )
            )
        bulk_create_ai_events(events)
        self.stdout.write(f"Added {len(events)} generations that declare and call a tool.")

    def _identity(self, team_id: int) -> None:
        events = [
            _generation(
                team_id,
                _trace_id("identity", index),
                distinct_id=f"person-{index}@example.com",
                minutes_ago=index + 1,
            )
            for index in range(3)
        ]
        bulk_create_ai_events(events)
        self.stdout.write(f"Added {len(events)} generations attributed to real distinct IDs.")

    def _spans(self, team_id: int) -> None:
        events = []
        for index in range(2):
            trace_id = _trace_id("spans", index)
            events.append(_generation(team_id, trace_id, distinct_id=trace_id, minutes_ago=index + 1))
            events.append(
                {
                    "event": "$ai_span",
                    "team_id": team_id,
                    "distinct_id": trace_id,
                    "timestamp": datetime.now(UTC) - timedelta(minutes=index + 1),
                    "properties": {
                        "$ai_trace_id": trace_id,
                        "$ai_parent_id": trace_id,
                        "$ai_span_name": "retrieve_documents",
                    },
                }
            )
        bulk_create_ai_events(events)
        self.stdout.write(f"Added {len(events)} events including spans nested under their trace.")

    def _report(self, team: Team) -> None:
        stats = fetch_checklist_stats(team)
        self.stdout.write("")
        self.stdout.write(f"{'check':>16}  {'status':<9} counts")
        self.stdout.write("-" * 72)
        for check in grade_checklist(stats, ()):
            counts = "  ".join(f"{name}={value}" for name, value in check.stats.items())
            self.stdout.write(f"{check.key.value:>16}  {check.status.value:<9} {counts}")
        self.stdout.write("")
