from typing import Dict, List, Tuple


def parse_filter(filters: Dict[str, str]) -> Tuple[str, Dict]:
    result = ""
    params = {}
    for idx, (k, v) in enumerate(filters.items()):
        result += "{cond}(ep.key = %(k{idx})s) AND (ep.value = %(v{idx})s)".format(
            idx=idx, cond=" AND " if idx > 0 else ""
        )
        params.update({"k{}".format(idx): k, "v{}".format(idx): v})
    return result, params
