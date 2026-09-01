from typing import Any

from posthog.schema_migrations.base import SchemaMigration

KIND_TO_FILTER_KEY = {
    "TrendsQuery": "trendsFilter",
    "StickinessQuery": "stickinessFilter",
}


class Migration(SchemaMigration):
    """Drop result customizations that do not match the active association mode.

    `resultCustomizations` must stay homogeneous: every entry keyed by series name
    (`assignmentBy: 'value'`) or every entry keyed by rank (`assignmentBy: 'position'`).
    A dict holding both matches neither side of the schema union, so the backend rejects
    the whole query. Switching the picker used to leave entries of the old kind behind, so
    stored insights can carry a mixed dict. Keep only the entries that match
    `resultCustomizationBy` (defaulting to `value`).
    """

    targets = {"TrendsQuery": 4, "StickinessQuery": 4}

    def transform(self, query: dict) -> dict:
        filter_key = KIND_TO_FILTER_KEY.get(str(query.get("kind")))
        if not filter_key:
            return query

        insight_filter = query.get(filter_key)
        if not isinstance(insight_filter, dict):
            return query

        result_customizations = insight_filter.get("resultCustomizations")
        if not isinstance(result_customizations, dict) or not result_customizations:
            return query

        target = insight_filter.get("resultCustomizationBy") or "value"
        kept: dict[str, Any] = {
            key: value for key, value in result_customizations.items() if self._assignment_by(value) == target
        }
        if kept == result_customizations:
            return query

        new_insight_filter = dict(insight_filter)
        new_insight_filter["resultCustomizations"] = kept
        query = dict(query)
        query[filter_key] = new_insight_filter
        return query

    @staticmethod
    def _assignment_by(value: Any) -> str:
        if isinstance(value, dict):
            return value.get("assignmentBy") or "value"
        return "value"
