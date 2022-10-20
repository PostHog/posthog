from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from django.http import HttpRequest, JsonResponse
from rest_framework.decorators import api_view


def get_sentry_stats(start_time: str, end_time: str) -> Tuple[dict, int]:
    url = f"https://sentry.io/api/0/organizations/posthog/issues/"
    token = "cb3d86f46c8e4ca592113d65c9adcac47482d32040674311bebe6ec11f714f1a"
    headers = {"Authorization": f"Bearer {token}"}

    params = {"start": start_time, "end": end_time, "sort": "freq", "utc": "true"}

    response = requests.get(url=url, headers=headers, params=params).json()

    counts = {}
    total_count = 0
    for item in response:
        counts[item["id"]] = {
            "count": int(item["count"]),
            "id": item["id"],
            "title": item["title"],
            "url": item["permalink"],
            "shortId": item["shortId"],
        }
        total_count += int(item["count"])

    return counts, total_count


def get_tagged_issues_stats(
    start_time: str, end_time: str, tags: Dict[str, str], target_issues: List[str]
) -> Dict[str, Any]:
    url = f"https://sentry.io/api/0/organizations/posthog/issues-stats/"
    token = "cb3d86f46c8e4ca592113d65c9adcac47482d32040674311bebe6ec11f714f1a"
    headers = {"Authorization": f"Bearer {token}"}

    query = "is:unresolved"
    for tag, value in tags.items():
        query += f" {tag}:{value}"

    params: Dict[str, Union[list, str]] = {
        "start": start_time,
        "end": end_time,
        "sort": "freq",
        "query": query,
        "utc": "true",
    }

    pagination_chunk_size = 25

    counts = {}

    for i in range(0, len(target_issues), pagination_chunk_size):
        groups = target_issues[i : i + pagination_chunk_size]
        params["groups"] = groups
        response = requests.get(url=url, headers=headers, params=params).json()

        # TODO: Confirm sentry always sends this information
        for item in response:
            counts[item["id"]] = {"id": item["id"]}
            counts[item["id"]]["filtered_count"] = item["filtered"]["count"]
            counts[item["id"]]["total_count"] = item["count"]

    return counts


def get_stats_for_timerange(
    base_start_time: str,
    base_end_time: str,
    target_start_time: str,
    target_end_time: str,
    tags: Optional[Dict[str, str]] = None,
) -> Tuple[int, int]:

    base_counts, base_total_count = get_sentry_stats(base_start_time, base_end_time)
    target_counts, target_total_count = get_sentry_stats(target_start_time, target_end_time)

    return base_total_count, target_total_count


@api_view(["GET"])
def sentry_stats(request: HttpRequest):

    try:
        current_time = datetime.utcnow()
        target_end_date = current_time.strftime("%Y-%m-%dT%H:%M:%S")
        target_start_date = (current_time - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")

        data, total_count = get_sentry_stats(target_start_date, target_end_date)

    except Exception as e:
        return JsonResponse({"error": "Error fetching stats from sentry", "exception": str(e)})

    return JsonResponse({"total_count": total_count, "data": data})
