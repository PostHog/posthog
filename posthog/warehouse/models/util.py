import re


def remove_named_tuples(type):
    """Remove named tuples from query"""
    from posthog.warehouse.models.table import CLICKHOUSE_HOGQL_MAPPING

    tokenified_type = re.split(r"(\W)", type)
    filtered_tokens = [
        token
        for token in tokenified_type
        if token == "Nullable" or (len(token) == 1 and not token.isalnum()) or token in CLICKHOUSE_HOGQL_MAPPING.keys()
    ]
    return "".join(filtered_tokens)
