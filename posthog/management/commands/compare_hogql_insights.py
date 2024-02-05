from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test if HogQL insights match their legacy counterparts"

    def handle(self, *args, **options):
        from typing import cast
        from posthog.schema import HogQLQueryModifiers, HogQLQueryResponse, MaterializationMode
        from posthog.models import Insight, Filter, RetentionFilter
        from posthog.models.filters import StickinessFilter
        from posthog.queries.retention import Retention
        from posthog.queries.trends.trends import Trends
        from posthog.queries.stickiness.stickiness import Stickiness
        from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
        from posthog.hogql_queries.query_runner import get_query_runner

        insights = (
            Insight.objects.filter(filters__contains={"insight": "RETENTION"}, saved=True, deleted=False)
            .order_by("id")
            .all()
        )
        for insight in insights[0:30]:
            try:
                print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")  # noqa: T201
                insight_type = insight.filters.get("insight")
                print(  # noqa: T201
                    f"Checking {insight_type} Insight {insight.id} {insight.short_id} - {insight.name} "
                    f"(team {insight.team_id})... Interval: {insight.filters.get('interval')}"
                )
                if insight.filters.get("aggregation_group_type_index", None) is not None:
                    del insight.filters["aggregation_group_type_index"]
                if insight_type == "STICKINESS":
                    sticky_filter = StickinessFilter(insight.filters, team=insight.team)
                    legacy_results = Stickiness().run(sticky_filter, insight.team)
                elif insight_type == "RETENTION":
                    retention_filter = RetentionFilter(insight.filters, team=insight.team)
                    legacy_results = Retention().run(retention_filter, insight.team)
                else:
                    # insight.team.week_start_day = 1
                    filter = Filter(insight.filters, team=insight.team)
                    legacy_results = Trends().run(filter, insight.team)
                for row in legacy_results:
                    if row.get("persons_urls"):
                        del row["persons_urls"]
                query = filter_to_query(insight.filters)
                modifiers = HogQLQueryModifiers(materializationMode=MaterializationMode.legacy_null_as_string)
                # insight.team.week_start_day = 1
                query_runner = get_query_runner(query, insight.team, modifiers=modifiers)
                hogql_results = cast(HogQLQueryResponse, query_runner.calculate()).results or []
                all_ok = True
                for legacy_result, hogql_result in zip(legacy_results, hogql_results):
                    if insight_type == "LIFECYCLE":
                        fields = ["data", "days", "count", "labels", "label", "status"]
                    elif insight_type == "RETENTION":
                        if legacy_result.get("date") != hogql_result.date:
                            all_ok = False
                            print("Date: ", legacy_result.get("date"), hogql_result.date)  # noqa: T201
                        if legacy_result.get("label") != hogql_result.label:
                            all_ok = False
                            print("Label: ", legacy_result.get("label"), hogql_result.label)  # noqa: T201
                        legacy_values = [c.get("count") for c in legacy_result.get("values") or []]
                        hogql_values = [c.count for c in hogql_result.values or []]
                        if legacy_values != hogql_values:
                            all_ok = False
                            print("Values: ", legacy_values, hogql_values)  # noqa: T201
                        continue
                    else:
                        fields = ["label", "count", "data", "labels", "days"]
                    for field in fields:
                        if legacy_result.get(field) != hogql_result.get(field):
                            print(  # noqa: T201
                                f"Insight https://app.posthog.com/insights/{insight.short_id}/edit"
                                f" ({insight.id}). MISMATCH in {legacy_result.get('status')} row, field {field}"
                            )
                            print("Legacy:", legacy_result.get(field))  # noqa: T201
                            print("HogQL:", hogql_result.get(field))  # noqa: T201
                            print("")  # noqa: T201
                            all_ok = False
                if all_ok:
                    print("ALL OK!")  # noqa: T201
            except Exception as e:
                print(f"Insight https://app.posthog.com/insights/{insight.short_id}/edit ({insight.id}). ERROR: {e}")  # noqa: T201
