from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Compare trend insights with trends-breakdown-fewer-array-ops flag enabled vs disabled"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            help="Team ID to filter insights (defaults to 2)",
            default=2,
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Number of insights to compare (default: 500)",
            default=500,
        )
        parser.add_argument(
            "--insight-id",
            type=int,
            help="Specific insight ID to compare",
            default=None,
        )

    def handle(self, *args, **options):
        import json
        from typing import cast
        from unittest.mock import patch

        from posthog.schema import HogQLQueryModifiers, HogQLQueryResponse, MaterializationMode
        from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
        from posthog.hogql_queries.query_runner import get_query_runner
        from posthog.models import Insight

        team_id = options["team_id"]
        limit = options["limit"]
        insight_id = options["insight_id"]

        if insight_id:
            insights = list(Insight.objects.filter(id=insight_id, deleted=False).all())
        else:
            insights = list(
                Insight.objects.filter(
                    filters__contains={"insight": "TRENDS"},
                    saved=True,
                    deleted=False,
                    team_id=team_id,
                )
                .order_by("created_at")
                .all()
            )
            # Filter to insights with breakdowns
            insights = [i for i in insights if "breakdown" in i.filters]
            # Filter out ActionsLineGraph display
            insights = [i for i in insights if i.filters.get("display") != "ActionsLineGraph"]

        self.stdout.write(f"Found {len(insights)} insights to compare")

        mismatches = 0
        errors = 0
        successes = 0

        for insight in insights[0:limit]:
            # Replace unsupported math functions
            for event in insight.filters.get("events", []):
                if event.get("math") in ("median", "p75", "p90", "p95", "p99"):
                    event["math"] = "sum"
            for event in insight.filters.get("actions", []):
                if event.get("math") in ("median", "p75", "p90", "p95", "p99"):
                    event["math"] = "sum"

            self.stdout.write("=" * 100)
            insight_type = insight.filters.get("insight")
            self.stdout.write(
                f"Checking {insight_type} Insight {insight.id} {insight.short_id} - {insight.name} "
                f"(team {insight.team_id})... Interval: {insight.filters.get('interval')}. {insight.filters.get('display')}"
            )

            # Run with feature flag DISABLED
            try:
                with patch(
                    "posthog.hogql_queries.insights.trends.trends_query_builder.TrendsQueryBuilder._team_flag_fewer_array_ops",
                    return_value=False,
                ):
                    query = filter_to_query(insight.filters)
                    modifiers = HogQLQueryModifiers(materializationMode=MaterializationMode.LEGACY_NULL_AS_STRING)
                    query_runner = get_query_runner(query, insight.team, modifiers=modifiers)
                    flag_disabled_results = cast(HogQLQueryResponse, query_runner.calculate()).results or []
            except Exception as e:
                url = f"https://us.posthog.com/project/{insight.team_id}/insights/{insight.short_id}/edit"
                self.stdout.write(self.style.ERROR(f"Flag DISABLED - Insight {url} ({insight.id}). ERROR: {e}"))
                self.stdout.write(json.dumps(insight.filters))
                errors += 1
                continue

            # Run with feature flag ENABLED
            try:
                with patch(
                    "posthog.hogql_queries.insights.trends.trends_query_builder.TrendsQueryBuilder._team_flag_fewer_array_ops",
                    return_value=True,
                ):
                    query = filter_to_query(insight.filters)
                    modifiers = HogQLQueryModifiers(materializationMode=MaterializationMode.LEGACY_NULL_AS_STRING)
                    query_runner = get_query_runner(query, insight.team, modifiers=modifiers)
                    flag_enabled_results = cast(HogQLQueryResponse, query_runner.calculate()).results or []
            except Exception as e:
                url = f"https://us.posthog.com/project/{insight.team_id}/insights/{insight.short_id}/edit"
                self.stdout.write(self.style.ERROR(f"Flag ENABLED - Insight {url} ({insight.id}). ERROR: {e}"))
                self.stdout.write(json.dumps(insight.filters))
                errors += 1
                continue

            # Compare results
            try:
                all_ok = True
                sorter = lambda x: (
                    "$$_posthog_breakdown_other_$$" if x.get("breakdown_value") == "Other" else x.get("breakdown_value")
                )
                sorted_disabled_results = sorted(flag_disabled_results, key=sorter)
                sorted_enabled_results = sorted(flag_enabled_results, key=sorter)

                if len(sorted_disabled_results) != len(sorted_enabled_results):
                    self.stdout.write(
                        self.style.ERROR(
                            f"Insight https://us.posthog.com/project/{insight.team_id}/insights/{insight.short_id}/edit"
                            f" ({insight.id}). MISMATCH in result count: "
                            f"disabled={len(sorted_disabled_results)}, enabled={len(sorted_enabled_results)}"
                        )
                    )
                    all_ok = False
                    mismatches += 1
                    continue

                for disabled_result, enabled_result in zip(sorted_disabled_results, sorted_enabled_results):
                    fields = ["label", "count", "aggregated_value", "data", "labels", "days", "breakdown_value"]
                    for field in fields:
                        disabled_value = disabled_result.get(field)
                        enabled_value = enabled_result.get(field)

                        if field == "count":
                            disabled_value = int(disabled_value or 0)
                            enabled_value = int(enabled_value or 0)
                        if field == "data":
                            disabled_value = [int(x) for x in disabled_value or []]
                            enabled_value = [int(x) for x in enabled_value or []]

                        if disabled_value != enabled_value:
                            # Handle known acceptable differences
                            if (
                                (field == "days" and enabled_value == [])
                                or (field == "labels" and insight.filters.get("interval") == "month")
                                or (field == "labels" and disabled_value == [] and enabled_value is None)
                                or (
                                    field == "label"
                                    and disabled_value == "Other"
                                    and enabled_value == "$$_posthog_breakdown_other_$$"
                                )
                                or (
                                    field == "label"
                                    and enabled_value == "Other"
                                    and disabled_value == "$$_posthog_breakdown_other_$$"
                                )
                            ):
                                continue

                            self.stdout.write(
                                self.style.ERROR(
                                    f"Insight https://us.posthog.com/project/{insight.team_id}/insights/{insight.short_id}/edit"
                                    f" ({insight.id}). MISMATCH in field '{field}'"
                                )
                            )
                            self.stdout.write(f"Flag DISABLED: {disabled_value}")
                            self.stdout.write(f"Flag ENABLED:  {enabled_value}")
                            self.stdout.write(json.dumps(insight.filters))
                            self.stdout.write("")
                            all_ok = False

                if all_ok:
                    self.stdout.write(self.style.SUCCESS("✓ ALL OK!"))
                    successes += 1
                else:
                    mismatches += 1

            except Exception as e:
                url = f"https://us.posthog.com/project/{insight.team_id}/insights/{insight.short_id}/edit"
                self.stdout.write(self.style.ERROR(f"Comparison Insight {url} ({insight.id}). ERROR: {e}"))
                self.stdout.write(json.dumps(insight.filters))
                errors += 1

        # Summary
        self.stdout.write("\n" + "=" * 100)
        self.stdout.write(self.style.SUCCESS(f"SUMMARY:"))
        self.stdout.write(f"  Total insights checked: {min(len(insights), limit)}")
        self.stdout.write(self.style.SUCCESS(f"  Successes: {successes}"))
        self.stdout.write(self.style.ERROR(f"  Mismatches: {mismatches}"))
        self.stdout.write(self.style.ERROR(f"  Errors: {errors}"))
