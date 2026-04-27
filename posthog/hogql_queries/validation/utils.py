import re

from posthog.types import InsightQueryNode


def get_query_insight_name(
    query: InsightQueryNode,
) -> str:
    query_kind = getattr(query, "kind", query.__class__.__name__).removesuffix("Query")
    humanized_query_kind = re.sub(r"(?<!^)(?=[A-Z][a-z])", " ", query_kind)
    return f"{humanized_query_kind} insights"
