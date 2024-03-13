from typing import cast
from django.core.management.base import BaseCommand
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelsQuery, HogQLQueryModifiers, MaterializationMode


class Command(BaseCommand):
    help = "Test if HogQL insights match their legacy counterparts"

    def handle(self, *args, **options):
        import json
        from posthog.models import Insight, Filter
        from posthog.queries.funnels import ClickhouseFunnel
        from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
        from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner

        IGNORED_INSIGHTS = [
            "qCf2qVXC",
            "8oivI5Si",
            "BGkyzMWV",
            "P5z6kXjT",
            "pEIfnI83",
            "3IY1Nhij",
            "u6ZPGsST",
            "-x48Xi9K",
            "BiW9wKf4",
            "9xcmkvsq",
            "EoBcQHus",
            "x4cC38rP",
            "0SLe31v1",
            "lx37J7XJ",
            "viGPH2P0",
            "nj6p2sTO",
            "vESGjN2P",
            "_xBU_hGJ",
            "5-B56Dvr",
            "ajtprsdX",
            "bqKiND7s",
            "X67ch-fD",
            "kwHeMuGG",
            "PvEZvJ7E",
            "ryFmelek",
            "nY_XOJGH",
            "SEJPBoya",
            "8MFOFasJ",
            "6WDMm0mQ",
            "0-xlBF7z",
            "7lx1xVyK",
            "rCNzPg4u",
            "E2w5B3uz",
            "RIPjUaQp",
            "yh-gVcLp",
            "bVpCCOCW",
            "H92CWNx7",
            "_XVLTYJh",
            "RKTr47ZY",
            "Nyvk3N8p",
            "7QOOBtaD",
            "6jA4uN4i",
            "oR0c6Gd6",
            "JpNtVpZb",
            "VS98D3k9",
            "0CVUZLki",
            "HB8ws1Rb",
            "fThH0WHC",
            "t648bVVo",
            "eyW4Sw4J",
            "TyhobRHV",
            "XptgB0nS",
            "lGa8G5jG",
        ]

        insights = (
            Insight.objects.filter(
                Q(filters__insight="FUNNELS")  # funnel insights
                & (Q(filters__funnel_viz_type="steps") | Q(filters__funnel_viz_type__isnull=True))  # steps viz
                & (Q(filters__funnel_order_type="ordered") | Q(filters__funnel_order_type__isnull=True))  # ordered
                # & Q(filters__breakdown__isnull=True)  # without breakdown
                # & Q(short_id="1jrKJ0n7")
                & ~Q(short_id__in=IGNORED_INSIGHTS) & Q(team_id=2),
                saved=True,
                deleted=False,
            )
            .order_by("id")
            .all()
        )

        for insight in insights[0:99]:
            print("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")  # noqa: T201
            print(f"Checking Funnel Insight {insight.pk} {insight.short_id} - {insight.name} ")  # noqa: T201

            BASE_URL = f"https://us.posthog.com/project/{insight.team.pk}"
            legacy_results, hogql_results, legacy_error, hogql_error = None, None, None, None

            try:
                filter = Filter(data=insight.filters, team=insight.team)
                legacy_results = ClickhouseFunnel(filter, insight.team).run()
            except ValidationError as e:
                legacy_error = e
            except Exception as e:
                url = f"{BASE_URL}/insights/{insight.short_id}/edit"
                print(f"LEGACY Insight {url} ({insight.pk}). ERROR: {e}")  # noqa: T201
                print(json.dumps(insight.filters))  # noqa: T201
                continue

            try:
                query = filter_to_query(insight.filters)
                query = cast(FunnelsQuery, query)
                modifiers = HogQLQueryModifiers(materializationMode=MaterializationMode.legacy_null_as_string)
                hogql_results = (
                    FunnelsQueryRunner(query=query, team=insight.team, modifiers=modifiers).calculate().results
                )
            except ValidationError as e:
                hogql_error = e
            except Exception as e:
                url = f"{BASE_URL}/insights/{insight.short_id}/edit"
                print(f"HogQL Insight {url} ({insight.pk}). ERROR: {e}")  # noqa: T201
                print(json.dumps(insight.filters))  # noqa: T201
                continue

            all_ok = True

            if legacy_error is not None:
                if hogql_error is None:
                    print(  # noqa: T201
                        f"Insight {BASE_URL}/insights/{insight.short_id}/edit"
                        f" ({insight.pk}). MISMATCH legacy has an error, but hogql has not: {legacy_error}"
                    )
                    all_ok = False
                elif hogql_error.detail != legacy_error.detail:
                    print(  # noqa: T201
                        f"Insight {BASE_URL}/insights/{insight.short_id}/edit"
                        f" ({insight.pk}). MISMATCH legacy error does not match hogql error"
                        f" legacy: {legacy_error}"
                        f" hogql: {hogql_error}"
                    )
                    all_ok = False
            elif hogql_error is not None:
                print(  # noqa: T201
                    f"Insight {BASE_URL}/insights/{insight.short_id}/edit"
                    f" ({insight.pk}). MISMATCH hogql has an error, but legacy has not: {hogql_error}"
                )
                all_ok = False

            else:
                assert legacy_results is not None
                assert hogql_results is not None

                for legacy_result, hogql_result in zip(legacy_results, hogql_results):  # type: ignore
                    if isinstance(legacy_result, list) and isinstance(hogql_result, list):
                        for sub_legacy_result, sub_hogql_result in zip(legacy_result, hogql_result):
                            compare_result(insight, sub_legacy_result, sub_hogql_result)
                    elif isinstance(legacy_result, list) or isinstance(hogql_result, list):
                        print("Error: Inconsistent data structures.")
                    else:
                        compare_result(insight, legacy_result, hogql_result)

            if all_ok:
                print("ALL OK!")  # noqa: T201


def compare_result(insight, legacy_result, hogql_result) -> bool:
    BASE_URL = f"https://us.posthog.com/project/{insight.team.pk}"
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

            print(  # noqa: T201
                f"Insight {BASE_URL}/insights/{insight.short_id}/edit"
                f" ({insight.pk}). MISMATCH in {legacy_result.get('order')} field {field}"
            )
            print("Legacy:", legacy_result.get(field))  # noqa: T201
            print("HogQL:", hogql_result.get(field))  # noqa: T201
            print("")  # noqa: T201
            return False

    return True
