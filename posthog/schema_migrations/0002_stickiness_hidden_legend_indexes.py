from posthog.schema import NodeKind
from posthog.schema_migrations.base import SchemaMigration


class Migration(SchemaMigration):
    """Convert 'hiddenLegendIndexes' to a new 'hidden' field of 'resultCustomizations'."""

    targets = {NodeKind.TRENDS_QUERY: 1, NodeKind.STICKINESS_QUERY: 1}

    def transform(self, query: dict) -> dict:
        # Only handle TrendsQuery
        if query.get("kind") != "TrendsQuery":
            return query

        trends_filter = query.get("trendsFilter")
        if trends_filter is None:
            return query

        hidden_indexes = trends_filter.get("hiddenLegendIndexes")
        result_customizations = trends_filter.get("resultCustomizations")

        # If no hiddenLegendIndexes, nothing to do
        if not hidden_indexes:
            return query

        # If resultCustomizations is None or not present, treat as empty dict
        if result_customizations is None:
            result_customizations = {}

        # If resultCustomizationBy == "value" or is empty, and has_value_assignment, we cannot convert hiddenLegendIndexes
        has_value_assignment = any(
            isinstance(v, dict) and v.get("assignmentBy") == "value" for v in result_customizations.values()
        )
        result_customization_by = trends_filter.get("resultCustomizationBy")
        if (result_customization_by == "value" or not result_customization_by) and has_value_assignment:
            # Remove hiddenLegendIndexes, leave resultCustomizations as is
            new_trends_filter = dict(trends_filter)
            new_trends_filter.pop("hiddenLegendIndexes", None)
            query = dict(query)
            query["trendsFilter"] = new_trends_filter
            return query

        # Otherwise, convert hiddenLegendIndexes to resultCustomizations by position
        new_result_customizations = dict(result_customizations)
        for idx in hidden_indexes:
            idx_str = str(idx)
            if idx_str not in new_result_customizations:
                new_result_customizations[idx_str] = {"assignmentBy": "position"}
            new_result_customizations[idx_str]["hidden"] = True

        new_trends_filter = dict(trends_filter)
        new_trends_filter["resultCustomizationBy"] = "position"
        new_trends_filter["resultCustomizations"] = new_result_customizations
        new_trends_filter.pop("hiddenLegendIndexes", None)

        query = dict(query)
        query["trendsFilter"] = new_trends_filter
        return query
