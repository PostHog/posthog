from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test if HogQL insights match their legacy counterparts"

    # 1133835
    def handle(self, *args, **options):
        import json
        from typing import cast

        from posthog.schema import HogQLQueryModifiers, HogQLQueryResponse, MaterializationMode

        from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
        from posthog.hogql_queries.query_runner import get_query_runner
        from posthog.models import Filter, Insight
        from posthog.queries.trends.trends import Trends

        insights = list(
            Insight.objects.filter(filters__contains={"insight": "TRENDS"}, saved=True, deleted=False, team_id=2)
            .order_by("created_at")
            .all()
        )
        # len(insights)
        insights = [i for i in insights if "breakdown" in i.filters]
        len(insights)
        # insights = [i for i in insights if "formula" not in i.filters]
        # len(insights)
        insights = [i for i in insights if i.filters.get("display") != "ActionsLineGraph"]
        len(insights)
        # insights = [i for i in insights if i.filters.get("display") == "ActionsLineGraphCumulative"]
        # len(insights)
        # insights = [i for i in insights if i.id > 1134855]
        # len(insights)
        for insight in insights[0:500]:
            for event in insight.filters.get("events", []):
                if event.get("math") in ("median", "p75", "p90", "p95", "p99"):
                    event["math"] = "sum"
            for event in insight.filters.get("actions", []):
                if event.get("math") in ("median", "p75", "p90", "p95", "p99"):
                    event["math"] = "sum"
            try:
                print(  # noqa: T201
                    "++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"
                )
                insight_type = insight.filters.get("insight")
                print(  # noqa: T201
                    f"Checking {insight_type} Insight {insight.id} {insight.short_id} - {insight.name} "
                    f"(team {insight.team_id})... Interval: {insight.filters.get('interval')}. {insight.filters.get('display')}"
                )
                if insight.filters.get("aggregation_group_type_index", None) is not None:
                    del insight.filters["aggregation_group_type_index"]
                filter = Filter(insight.filters, team=insight.team)
                legacy_results = Trends().run(filter, insight.team)
                for row in legacy_results:
                    if row.get("persons_urls"):
                        del row["persons_urls"]
            except Exception as e:
                url = f"https://us.posthog.com/project/{insight.team_id}/insights/{insight.short_id}/edit"
                print(f"LEGACY Insight {url} ({insight.id}). ERROR: {e}")  # noqa: T201
                print(json.dumps(insight.filters))  # noqa: T201
                continue
            try:
                query = filter_to_query(insight.filters)
                modifiers = HogQLQueryModifiers(materializationMode=MaterializationMode.LEGACY_NULL_AS_STRING)
                query_runner = get_query_runner(query, insight.team, modifiers=modifiers)
                hogql_results = cast(HogQLQueryResponse, query_runner.calculate()).results or []
            except Exception as e:
                url = f"https://us.posthog.com/project/{insight.team_id}/insights/{insight.short_id}/edit"
                print(f"HogQL Insight {url} ({insight.id}). ERROR: {e}")  # noqa: T201
                print(json.dumps(insight.filters))  # noqa: T201
                continue
            try:
                all_ok = True
                sorter = lambda x: (
                    "$$_posthog_breakdown_other_$$" if x.get("breakdown_value") == "Other" else x.get("breakdown_value")
                )
                sorted_legacy_results = sorted(
                    legacy_results,
                    key=sorter,
                )
                sorted_hogql_results = sorted(hogql_results, key=lambda x: x.get("breakdown_value"))
                for legacy_result, hogql_result in zip(sorted_legacy_results, sorted_hogql_results):
                    fields = ["label", "count", "aggregated_value", "data", "labels", "days"]
                    for field in fields:
                        legacy_value = legacy_result.get(field)
                        hogql_value = hogql_result.get(field)
                        if field == "count":
                            legacy_value = int(legacy_value or 0)
                            hogql_value = int(hogql_value)
                        if field == "data":
                            legacy_value = [int(x) for x in legacy_value or []]
                            hogql_value = [int(x) for x in hogql_value or []]
                        if legacy_value != hogql_value:
                            if (
                                (field == "days" and hogql_value == [])
                                or (field == "labels" and insight.filters.get("interval") == "month")
                                or (field == "labels" and legacy_value == [] and hogql_value is None)
                                or (
                                    field == "label"
                                    and legacy_value == "Other"
                                    and hogql_value == "$$_posthog_breakdown_other_$$"
                                )
                            ):
                                continue
                            print(  # noqa: T201
                                f"Insight https://us.posthog.com/project/{insight.team_id}/insights/{insight.short_id}/edit"
                                f" ({insight.id}). MISMATCH in {legacy_result.get('status')} row, field {field}"
                            )
                            print("Legacy:", legacy_value)  # noqa: T201
                            print("HogQL: ", hogql_value)  # noqa: T201
                            print(json.dumps(insight.filters))  # noqa: T201
                            print("")  # noqa: T201
                            all_ok = False
                if all_ok:
                    print("ALL OK!")  # noqa: T201
            except Exception as e:
                url = f"https://us.posthog.com/project/{insight.team_id}/insights/{insight.short_id}/edit"
                print(f"Comparison Insight {url} ({insight.id}). ERROR: {e}")  # noqa: T201
                print(json.dumps(insight.filters))  # noqa: T201
