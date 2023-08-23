import json
from typing import Optional, Dict

from sentry_sdk import capture_message


def temporary_filters_from_request(request_query_params) -> Optional[Dict]:
    temporary_filters = request_query_params.get("temporary_filters", None)
    if temporary_filters:
        try:
            temporary_filters = json.loads(temporary_filters)
        except TypeError:
            capture_message(
                "Temporary filters are not valid JSON",
                level="warning",
                extras={
                    "temporary_filters": temporary_filters,
                },
            )
            temporary_filters = None
    return temporary_filters
