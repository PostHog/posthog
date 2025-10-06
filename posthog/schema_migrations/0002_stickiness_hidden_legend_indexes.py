from posthog.schema_migrations.base import SchemaMigration

KIND_TO_FILTER_KEY = {
    "TrendsQuery": "trendsFilter",
    "StickinessQuery": "stickinessFilter",
}


class Migration(SchemaMigration):
    """Convert 'hiddenLegendIndexes' to a new 'hidden' field of 'resultCustomizations'."""

    targets = {"TrendsQuery": 1, "StickinessQuery": 1}

    def transform(self, query: dict) -> dict:
        filter_key = KIND_TO_FILTER_KEY.get(str(query.get("kind")))
        if not filter_key:
            return query

        insight_filter = query.get(filter_key)
        if not isinstance(insight_filter, dict):
            return query

        hidden_indexes = insight_filter.get("hiddenLegendIndexes")
        result_customizations = insight_filter.get("resultCustomizations") or {}
        result_customization_by = insight_filter.get("resultCustomizationBy")

        # Nothing to do, if there are no hiddenLegendIndexes
        if not hidden_indexes:
            return query

        # Handle case where we have resultCustomizations by value
        has_value_assignment = any(
            isinstance(v, dict) and v.get("assignmentBy") == "value" for v in result_customizations.values()
        )
        if (result_customization_by == "value" or not result_customization_by) and has_value_assignment:
            # Allow conversion if there are no breakdown and no compare
            if not self._has_breakdown(query=query) and not self._has_compare(query=query):
                # Convert hiddenLegendIndexes to resultCustomizations by value
                new_result_customizations = dict(result_customizations)
                for idx in hidden_indexes:
                    idx_key = f'{{"series":{idx}}}'
                    if idx_key not in new_result_customizations:
                        new_result_customizations[idx_key] = {"assignmentBy": "value"}
                    new_result_customizations[idx_key]["hidden"] = True
                new_insight_filter = dict(insight_filter)
                new_insight_filter["resultCustomizationBy"] = "value"
                new_insight_filter["resultCustomizations"] = new_result_customizations
                new_insight_filter.pop("hiddenLegendIndexes", None)
                query = dict(query)
                query[filter_key] = new_insight_filter
                return query
            # Otherwise remove hiddenLegendIndexes
            new_insight_filter = dict(insight_filter)
            new_insight_filter.pop("hiddenLegendIndexes", None)
            query = dict(query)
            query[filter_key] = new_insight_filter
            return query

        # Handle case where we do not have resultCustomizations by value
        new_result_customizations = dict(result_customizations)
        for idx in hidden_indexes:
            idx_str = str(idx)
            if idx_str not in new_result_customizations:
                new_result_customizations[idx_str] = {"assignmentBy": "position"}
            new_result_customizations[idx_str]["hidden"] = True

        new_insight_filter = dict(insight_filter)
        new_insight_filter["resultCustomizationBy"] = "position"
        new_insight_filter["resultCustomizations"] = new_result_customizations
        new_insight_filter.pop("hiddenLegendIndexes", None)

        query = dict(query)
        query[filter_key] = new_insight_filter
        return query

    @staticmethod
    def _has_breakdown(query: dict) -> bool:
        breakdown_filter = query.get("breakdownFilter")
        if not breakdown_filter:
            return False
        if breakdown_filter.get("breakdown_type") and breakdown_filter.get("breakdown"):
            return True
        breakdowns = breakdown_filter.get("breakdowns")
        if isinstance(breakdowns, list) and len(breakdowns) > 0:
            return True
        return False

    @staticmethod
    def _has_compare(query: dict) -> bool:
        compare_filter = query.get("compareFilter")
        if not compare_filter:
            return False
        return compare_filter.get("compare") is True
