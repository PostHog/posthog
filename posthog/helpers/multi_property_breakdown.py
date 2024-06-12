import copy
from typing import Any, Union

funnel_with_breakdown_type = list[list[dict[str, Any]]]
possible_funnel_results_types = Union[funnel_with_breakdown_type, list[dict[str, Any]], dict[str, Any]]


def protect_old_clients_from_multi_property_default(
    request_filter: dict[str, Any], result: possible_funnel_results_types
) -> possible_funnel_results_types:
    """
    Implementing multi property breakdown will default breakdown to a list even if it is received as a string.
    This is a breaking change for clients.
    Clients which do not have multi property breakdown enabled will send a single breakdown as a string
    This method checks if the request has come in that format and "unboxes" the list
    to avoid breaking that client

    Funnel results can have three shapes
    * A Dict
    * A List containing one or more Dicts
    * A List containing (exactly one) lists of Dicts

    :param request_filter: the data in the request
    :param result: the query result which may contain an unwanted array breakdown
    :return:
    """

    if isinstance(result, dict) or (len(result) > 1) and isinstance(result[0], dict):
        return result

    is_breakdown_request = (
        "insight" in request_filter
        and request_filter["insight"] == "FUNNELS"
        and "breakdown_type" in request_filter
        and request_filter["breakdown_type"] in ["person", "event"]
    )
    is_breakdown_result = isinstance(result, list) and len(result) > 0 and isinstance(result[0], list)

    is_single_property_breakdown = (
        is_breakdown_request
        and "breakdown" in request_filter
        and isinstance(request_filter["breakdown"], str)
        and is_breakdown_result
    )
    is_multi_property_breakdown = is_breakdown_request and "breakdowns" in request_filter and is_breakdown_result

    if is_single_property_breakdown or is_multi_property_breakdown:
        copied_result = copy.deepcopy(result)
        for series_index in range(len(result)):
            copied_series = copied_result[series_index]

            if isinstance(copied_series, list):
                for data_index in range(len(copied_series)):
                    copied_item = copied_series[data_index]

                    if is_single_property_breakdown:
                        if copied_item.get("breakdown") and isinstance(copied_item["breakdown"], list):
                            copied_item["breakdown"] = copied_item["breakdown"][0]
                        if copied_item.get("breakdown_value") and isinstance(copied_item["breakdown_value"], list):
                            copied_item["breakdown_value"] = copied_item["breakdown_value"][0]

                    if is_multi_property_breakdown:
                        breakdowns = copied_item.pop("breakdown", None)
                        copied_item["breakdowns"] = breakdowns
        return copied_result
    else:
        return result
