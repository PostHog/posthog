from posthog.schema import NodeKind
from posthog.schema_migrations.base import SchemaMigration


class Migration(SchemaMigration):
    """Convert 'hiddenLegendIndexes' to a new 'hidden' field of 'resultCustomizations'."""

    targets = {NodeKind.TRENDS_QUERY: 1, NodeKind.STICKINESS_QUERY: 1}

    def transform(self, query: dict) -> dict:
        # Only handle TrendsQuery and StickinessQuery
        kind = query.get("kind")
        if kind == "TrendsQuery":
            filter_key = "trendsFilter"
        elif kind == "StickinessQuery":
            filter_key = "stickinessFilter"
        else:
            return query

        insight_filter = query.get(filter_key)
        if insight_filter is None:
            return query

        hidden_indexes = insight_filter.get("hiddenLegendIndexes")
        result_customizations = insight_filter.get("resultCustomizations")

        # If no hiddenLegendIndexes, nothing to do
        if not hidden_indexes:
            return query

        # If resultCustomizations is None or not present, treat as empty dict
        if result_customizations is None:
            result_customizations = {}

        # Helper: check for breakdown
        def has_breakdown():
            breakdown_filter = query.get("breakdownFilter")
            if not breakdown_filter:
                return False
            if breakdown_filter.get("breakdown_type") and breakdown_filter.get("breakdown"):
                return True
            breakdowns = breakdown_filter.get("breakdowns")
            if isinstance(breakdowns, list) and len(breakdowns) > 0:
                return True
            return False

        # Helper: check for compare
        def has_compare():
            compare_filter = query.get("compareFilter")
            if not compare_filter:
                return False
            return compare_filter.get("compare") is True

        # If resultCustomizationBy == "value" or is empty, and has_value_assignment, we cannot convert hiddenLegendIndexes
        has_value_assignment = any(
            isinstance(v, dict) and v.get("assignmentBy") == "value" for v in result_customizations.values()
        )
        result_customization_by = insight_filter.get("resultCustomizationBy")
        if (result_customization_by == "value" or not result_customization_by) and has_value_assignment:
            # Allow conversion if no breakdown and no compare
            if not has_breakdown() and not has_compare():
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
            # Remove hiddenLegendIndexes, leave resultCustomizations as is
            new_insight_filter = dict(insight_filter)
            new_insight_filter.pop("hiddenLegendIndexes", None)
            query = dict(query)
            query[filter_key] = new_insight_filter
            return query

        # Otherwise, convert hiddenLegendIndexes to resultCustomizations by position
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
