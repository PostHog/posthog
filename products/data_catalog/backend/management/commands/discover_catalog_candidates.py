import json
import dataclasses
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from posthog.models import Team

from products.data_catalog.backend.logic.discovery import (
    DEFAULT_MAX_METRIC_CANDIDATES,
    DEFAULT_MAX_RELATIONSHIP_CANDIDATES,
    DEFAULT_MIN_JOIN_OCCURRENCES,
    DEFAULT_MIN_SQL_RUNS,
    DEFAULT_WINDOW_DAYS,
    apply_candidates,
    discover_candidates,
)
from products.data_catalog.backend.logic.discovery_clustering import (
    DEFAULT_DISTANCE_THRESHOLD,
    apply_semantic_clustering,
    team_embedder,
)


class Command(BaseCommand):
    help = (
        "Discover candidate data catalog metrics and relationships from a team's query usage "
        "(query log, insights, dashboards). Dry-run by default; --write persists them as proposed rows."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
        parser.add_argument("--min-sql-runs", type=int, default=DEFAULT_MIN_SQL_RUNS)
        parser.add_argument("--min-join-occurrences", type=int, default=DEFAULT_MIN_JOIN_OCCURRENCES)
        parser.add_argument("--max-metric-candidates", type=int, default=DEFAULT_MAX_METRIC_CANDIDATES)
        parser.add_argument("--max-relationship-candidates", type=int, default=DEFAULT_MAX_RELATIONSHIP_CANDIDATES)
        parser.add_argument("--write", action="store_true", help="Persist candidates as proposed catalog rows.")
        parser.add_argument("--ai-model", type=str, default="", help="Model attribution recorded on written metrics.")
        parser.add_argument(
            "--no-semantic-clustering",
            action="store_true",
            help="Skip embedding-based merging of near-duplicate metric candidates.",
        )
        parser.add_argument("--distance-threshold", type=float, default=DEFAULT_DISTANCE_THRESHOLD)

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.get(pk=options["team_id"])
        report = discover_candidates(
            team,
            days=options["days"],
            min_sql_runs=options["min_sql_runs"],
            min_join_occurrences=options["min_join_occurrences"],
            max_metric_candidates=options["max_metric_candidates"],
            max_relationship_candidates=options["max_relationship_candidates"],
        )
        if not options["no_semantic_clustering"]:
            report = apply_semantic_clustering(
                report, embed_texts=team_embedder(team), distance_threshold=options["distance_threshold"]
            )
        self.stdout.write(json.dumps(dataclasses.asdict(report), indent=2, default=str))
        if options["write"]:
            summary = apply_candidates(report, team=team, ai_model=options["ai_model"])
            self.stdout.write(json.dumps(dataclasses.asdict(summary), indent=2, default=str))
