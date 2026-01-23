from typing import Any, Optional

from django.conf import settings

SCOPE_TO_PATH_MAPPING: dict[str, str] = {
    "Replay": "/replay/{item_id}",
    "Notebook": "/notebooks/{item_id}",
    "Insight": "/insights/{item_id}",
    "FeatureFlag": "/feature_flags/{item_id}",
    "Dashboard": "/dashboard/{item_id}",
    "Survey": "/surveys/{item_id}",
    "Experiment": "/experiments/{item_id}",
}


def build_comment_item_url(scope: str, item_id: Optional[str], slug: Optional[str] = None) -> str:
    if slug:
        url = f"{settings.SITE_URL}{slug}"
    elif scope in SCOPE_TO_PATH_MAPPING and item_id:
        path = SCOPE_TO_PATH_MAPPING[scope].format(item_id=item_id)
        url = f"{settings.SITE_URL}{path}"
    else:
        url = settings.SITE_URL

    if "#panel=discussion" not in url:
        url = f"{url}#panel=discussion"

    return url


def extract_plain_text_from_rich_content(rich_content: Optional[dict]) -> str:
    if not rich_content:
        return ""

    text_parts: list[str] = []

    def traverse(node: Any) -> None:
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "text":
                text_parts.append(node.get("text", ""))
            elif node_type == "ph-mention":
                attrs = node.get("attrs", {})
                label = attrs.get("label", "")
                if label:
                    text_parts.append(f"@{label}")
            elif node_type == "hardBreak":
                text_parts.append("\n")

            for value in node.values():
                if isinstance(value, dict | list):
                    traverse(value)
        elif isinstance(node, list):
            for item in node:
                traverse(item)

    traverse(rich_content)
    return "".join(text_parts)
