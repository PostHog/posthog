from django.core.management.base import BaseCommand

from posthog.schema import HogQLQueryModifiers, MaterializationMode


class Command(BaseCommand):
    help = "Test if HogQL insights match their legacy counterparts"

    def handle(self, *args, **options):
        from posthog.models import Insight, Filter
        from posthog.queries.trends.trends import Trends
        from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
        from posthog.hogql_queries.query_runner import get_query_runner

        insights = (
            Insight.objects.filter(filters__contains={"insight": "LIFECYCLE"}, saved=True, deleted=False)
            .order_by("id")
            .all()
        )

        for insight in insights[0:10]:
            print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")  # noqa: T201
            print(  # noqa: T201
                f"Checking Lifecycle Insight {insight.id} {insight.short_id} - {insight.name} "
                f"(team {insight.team_id})... Interval: {insight.filters.get('interval')}"
            )
            if insight.filters.get("aggregation_group_type_index", None) is not None:
                del insight.filters["aggregation_group_type_index"]
            filter = Filter(insight.filters, team=insight.team)
            legacy_results = Trends().run(filter, insight.team)
            for row in legacy_results:
                if row.get("persons_urls"):
                    del row["persons_urls"]
            query = filter_to_query(insight.filters)
            modifiers = HogQLQueryModifiers(materializationMode=MaterializationMode.legacy_null_as_string)
            query_runner = get_query_runner(query, insight.team, modifiers=modifiers)
            hogql_results = query_runner.calculate().results
            order = {"new": 1, "returning": 2, "resurrecting": 3, "dormant": 4}
            legacy_results = sorted(legacy_results, key=lambda k: order[k["status"]])
            hogql_results = sorted(hogql_results, key=lambda k: order[k["status"]])
            all_ok = True
            for legacy_result, hogql_result in zip(legacy_results, hogql_results):
                fields = ["data", "days", "count", "labels", "label", "status"]
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
