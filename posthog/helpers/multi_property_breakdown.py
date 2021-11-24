import copy
from typing import Any, Dict, List


def protect_old_clients_from_multi_property_default(
    data: Dict[str, Any], result: List[List[Dict[str, Any]]]
) -> List[List[Dict[str, Any]]]:
    """
    Implementing multi property breakdown will default breakdown to a list even if it is received as a string.
    This is a breaking change for clients.
    Clients which do not have multi property breakdown enabled will send a single breakdown as a string
    This method checks if the request has come in that format and "unboxes" the list
    to avoid breaking that client
    :param data: the data in the request
    :param result: the query result which may contain an unwanted array breakdown
    :return:
    """

    is_single_property_breakdown = (
        "insight" in data
        and data["insight"] == "FUNNELS"
        and "breakdown_type" in data
        and data["breakdown_type"] in ["person", "event"]
        and "breakdown" in data
        and isinstance(data["breakdown"], str)
    )
    is_multi_property_breakdown = (
        "insight" in data
        and data["insight"] == "FUNNELS"
        and "breakdown_type" in data
        and data["breakdown_type"] in ["person", "event"]
        and "breakdowns" in data
    )
    if is_single_property_breakdown or is_multi_property_breakdown:
        copied_result = copy.deepcopy(result)
        for series_index, series in enumerate(result):
            for data_index, data in enumerate(series):
                if is_single_property_breakdown:
                    if isinstance(data["breakdown"], List):
                        copied_result[series_index][data_index]["breakdown"] = data["breakdown"][0]
                    if isinstance(data["breakdown_value"], List):
                        copied_result[series_index][data_index]["breakdown_value"] = data["breakdown_value"][0]
                if is_multi_property_breakdown:
                    breakdowns = copied_result[series_index][data_index].pop("breakdown", None)
                    copied_result[series_index][data_index]["breakdowns"] = breakdowns
        return copied_result
    else:
        return result
