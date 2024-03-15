# ruff: noqa: T201
from datetime import datetime
from django.core.management.base import BaseCommand
from typing import cast
from django.db.models import Q
from rest_framework.exceptions import ValidationError
from posthog.queries.funnels.funnel_time_to_convert import ClickhouseFunnelTimeToConvert
from posthog.queries.funnels.funnel_trends import ClickhouseFunnelTrends
from posthog.schema import FunnelsQuery, HogQLQueryModifiers, MaterializationMode
from posthog.models import Insight, Filter

from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner

from posthog.constants import FunnelOrderType, FunnelVizType
from posthog.queries.funnels.utils import get_funnel_order_class


def get_legacy_class(filter: Filter):
    if filter.funnel_viz_type == FunnelVizType.TRENDS:
        klass = ClickhouseFunnelTrends
    elif filter.funnel_viz_type == FunnelVizType.TIME_TO_CONVERT:
        klass = ClickhouseFunnelTimeToConvert
    else:
        klass = get_funnel_order_class(filter)

    return klass


class Command(BaseCommand):
    help = "Test if HogQL insights match their legacy counterparts"

    def handle(self, *args, **options):

        IGNORED_INSIGHTS = []

        insights = (
            Insight.objects.filter(
                Q(filters__insight="FUNNELS")  # funnel insights
                ## funnel viz type (pick one):
                # & (Q(filters__funnel_viz_type="steps") | Q(filters__funnel_viz_type__isnull=True))  # steps viz
                # & Q(filters__funnel_viz_type="time_to_convert")  # time to convert viz
                # & Q(filters__funnel_viz_type="trends")  # trends viz
                ## funnel order type (pick one):
                # & (Q(filters__funnel_order_type="ordered") | Q(filters__funnel_order_type__isnull=True))  # ordered
                # & Q(filters__funnel_order_type="unordered")  # unordered
                # & Q(filters__funnel_order_type="strict")  # strict
                ## breakdowns
                # & Q(filters__breakdown__isnull=True)  # without breakdown
                # & Q(short_id="v1trHpS3"),
                & ~Q(short_id__in=IGNORED_INSIGHTS) & Q(team_id=1),
                saved=True,
                deleted=False,
            )
            .order_by("id")
            .all()
        )

        for insight in insights[0:99]:
            BASE_URL = f"https://us.posthog.com/project/{insight.team.pk}"
            print("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            print(f'Checking Funnel Insight {insight.pk} {insight.short_id} - "{insight.name or insight.derived_name}"')
            print(f"\t{BASE_URL}/insights/{insight.short_id}/edit")
            legacy_results, hogql_results, legacy_error, hogql_error = None, None, None, None
            filter = Filter(data=insight.filters, team=insight.team)
            query = filter_to_query(insight.filters)
            query = cast(FunnelsQuery, query)
            modifiers = HogQLQueryModifiers(materializationMode=MaterializationMode.legacy_null_as_string)
            funnel_order_type = filter.funnel_order_type or FunnelOrderType.ORDERED
            funnel_viz_type = filter.funnel_viz_type or FunnelVizType.STEPS
            print(f"\t{funnel_order_type} {funnel_viz_type}")

            try:
                now = datetime.now()
                funnel_class = get_legacy_class(filter)
                legacy_results = funnel_class(filter, insight.team).run()
                legacy_time = (datetime.now() - now).total_seconds()
            except ValidationError as e:
                legacy_error = e
            except Exception as e:
                url = f"{BASE_URL}/insights/{insight.short_id}/edit"
                print(f"LEGACY Insight ERROR: {e}")
                continue

            try:
                now = datetime.now()
                hogql_results = (
                    FunnelsQueryRunner(query=query, team=insight.team, modifiers=modifiers).calculate().results
                )
                hogql_time = (datetime.now() - now).total_seconds()
            except ValidationError as e:
                if e.get_full_details()[0]["message"] == "Funnels require at least two steps before calculating.":
                    print("Funnels require at least two steps before calculating.")
                    continue
                hogql_error = e
            except Exception as e:
                url = f"{BASE_URL}/insights/{insight.short_id}/edit"
                print(f"HogQL Insight ERROR: {e}")
                continue

            all_ok = True

            if legacy_error is not None:
                if hogql_error is None:
                    print(
                        f"Insight {BASE_URL}/insights/{insight.short_id}/edit"
                        f" ({insight.pk}). MISMATCH legacy has an error, but hogql has not: {legacy_error}"
                    )
                    all_ok = False
                elif hogql_error.detail != legacy_error.detail:
                    print(
                        f"Insight {BASE_URL}/insights/{insight.short_id}/edit"
                        f" ({insight.pk}). MISMATCH legacy error does not match hogql error"
                        f" legacy: {legacy_error}"
                        f" hogql: {hogql_error}"
                    )
                    all_ok = False
            elif hogql_error is not None:
                print(
                    f"Insight {BASE_URL}/insights/{insight.short_id}/edit"
                    f" ({insight.pk}). MISMATCH hogql has an error, but legacy has not: {hogql_error}"
                )
                all_ok = False

            else:
                assert legacy_results is not None
                assert hogql_results is not None

                if filter.funnel_viz_type == "time_to_convert":
                    if legacy_results["average_conversion_time"] != hogql_results.average_conversion_time:
                        all_ok = False
                        print("MISMATCH in average_conversion_time")
                        print("Legacy:", legacy_results["average_conversion_time"])
                        print("HogQL:", hogql_results.average_conversion_time)

                    bin_mismatch = False
                    for legacy, hogql in zip(legacy_results["bins"], hogql_results.bins):
                        if int(legacy[0]) != hogql[0]:
                            all_ok = False
                            bin_mismatch = True

                        if legacy[1] != hogql[1]:
                            all_ok = False
                            bin_mismatch = True

                    if bin_mismatch:
                        print(f"MISMATCH in bins")
                        print("Legacy:", legacy_results["bins"])
                        print("HogQL:", hogql_results.bins)
                elif filter.funnel_viz_type == "trends":
                    for legacy_result, hogql_result in zip(legacy_results, hogql_results):
                        for field in ["count", "data", "days", "labels"]:
                            legacy = legacy_result[field]
                            hogql = hogql_result[field]

                            if legacy != hogql:
                                print(f"MISMATCH in field {field}")
                                print("Legacy:", legacy)
                                print("HogQL:", hogql)
                                print("")
                                all_ok = False
                else:
                    sorted_legacy_results = legacy_results
                    sorted_hogql_results = hogql_results

                    if isinstance(legacy_results[0], list):
                        sorter = lambda step: (step[0]["breakdown_value"])
                        sorted_legacy_results = sorted(legacy_results, key=sorter)
                        sorted_hogql_results = sorted(hogql_results, key=sorter)

                    for legacy_result, hogql_result in zip(sorted_legacy_results, sorted_hogql_results):  # type: ignore
                        if isinstance(legacy_result, list) and isinstance(hogql_result, list):
                            for sub_legacy_result, sub_hogql_result in zip(legacy_result, hogql_result):
                                if compare_result(insight, sub_legacy_result, sub_hogql_result) is False:
                                    all_ok = False
                        elif isinstance(legacy_result, list) or isinstance(hogql_result, list):
                            print("Error: Inconsistent data structures.")
                        else:
                            if compare_result(insight, legacy_result, hogql_result) is False:
                                all_ok = False

            if all_ok:
                diff = hogql_time - legacy_time
                percentage = hogql_time / legacy_time
                significant = percentage > 1.1 and diff > 1
                warn = ""
                if significant:
                    warn = "-- /!\\ {:.1%} /!\\".format(percentage)
                print(f"\tLegacy time: {legacy_time} HogQL time: {hogql_time} {warn}")
                print("ALL OK!")


def compare_result(insight, legacy_result, hogql_result) -> bool:
    fields = [
        "action_id",
        "name",
        "custom_name",
        "order",
        "people",
        "count",
        "type",
        "average_conversion_time",
        "median_conversion_time",
        # "converted_people_url",
        # "dropped_people_url",
        "breakdown",
        "breakdown_value",
    ]
    for field in fields:
        legacy = legacy_result.get(field)
        hogql = hogql_result.get(field)

        if legacy != hogql:
            # ignore differences in action_id types (stringified numbers in legacy)
            if field == "action_id" and int(legacy) == hogql:
                continue
            # ignore differences after 1 decimal place for average_conversion_time
            if field == "average_conversion_time" and round(legacy, 1) == round(hogql, 1):
                continue

            print(f"MISMATCH in {legacy_result.get('order')} field {field}")
            print("Legacy:", legacy_result.get(field))
            print("HogQL:", hogql_result.get(field))
            print("")
            return False

    return True
