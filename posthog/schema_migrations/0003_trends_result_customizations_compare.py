import json
from typing import Any, Optional

from posthog.schema_migrations.base import SchemaMigration

KIND_TO_FILTER_KEY = {
    "TrendsQuery": "trendsFilter",
    "StickinessQuery": "stickinessFilter",
}


class Migration(SchemaMigration):
    """Merge per-compare-period result customizations into a single base-series entry.

    Customization keys used to include `compare_label`, giving the current and previous
    period of a series independent entries. The frontend now keys customizations by the
    base series only, so both periods share one entry:
    - by value: `compare_label` is stripped from the key. When entries conflict, the one
      matching the stored compare state wins ("current" if compare is on, the unlabelled
      one otherwise). "previous"-labelled entries are dropped — carrying e.g. `hidden`
      over to the pair would hide the current period too.
    - by position: with compare on, previous-period datasets used to occupy positions
      offset by the number of base series. Offset entries are shifted back, existing
      base entries win. Skipped with breakdowns, where the offset is data-dependent.
    """

    targets = {"TrendsQuery": 2, "StickinessQuery": 2}

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

        compare_on = self._has_compare(query)

        if insight_filter.get("resultCustomizationBy") == "position":
            new_result_customizations = self._transform_by_position(query, insight_filter, result_customizations)
        else:
            new_result_customizations = self._transform_by_value(result_customizations, compare_on)

        if new_result_customizations == result_customizations:
            return query

        new_insight_filter = dict(insight_filter)
        new_insight_filter["resultCustomizations"] = new_result_customizations
        query = dict(query)
        query[filter_key] = new_insight_filter
        return query

    def _transform_by_value(self, result_customizations: dict, compare_on: bool) -> dict:
        merged: dict[str, Any] = {}
        for key, value in result_customizations.items():
            parsed = self._parse_value_key(key)
            if parsed is None or "compare_label" not in parsed:
                # already a base key; an earlier "current" entry wins when compare is on
                if key in merged and compare_on:
                    continue
                merged[key] = value
                continue

            label = parsed.pop("compare_label")
            if label != "current":
                continue

            base_key = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
            if base_key in merged and not compare_on:
                continue
            merged[base_key] = value
        return merged

    def _transform_by_position(self, query: dict, insight_filter: dict, result_customizations: dict) -> dict:
        if not self._has_compare(query) or self._has_breakdown(query):
            return result_customizations

        base_series_count = self._base_series_count(query, insight_filter)
        if not base_series_count:
            return result_customizations

        remapped: dict[str, Any] = {}
        offset_entries: list[tuple[int, Any]] = []
        for key, value in result_customizations.items():
            position = self._parse_position_key(key)
            if position is None or position < base_series_count:
                remapped[key] = value
            else:
                offset_entries.append((position, value))

        for position, value in offset_entries:
            target = str(position - base_series_count)
            if target not in remapped:
                remapped[target] = value
        return remapped

    @staticmethod
    def _parse_value_key(key: str) -> Optional[dict]:
        try:
            parsed = json.loads(key)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _parse_position_key(key: str) -> Optional[int]:
        try:
            return int(key)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _base_series_count(query: dict, insight_filter: dict) -> int:
        formula_nodes = insight_filter.get("formulaNodes")
        if isinstance(formula_nodes, list) and formula_nodes:
            return len(formula_nodes)
        formulas = insight_filter.get("formulas")
        if isinstance(formulas, list) and formulas:
            return len(formulas)
        if insight_filter.get("formula"):
            return 1
        series = query.get("series")
        return len(series) if isinstance(series, list) else 0

    @staticmethod
    def _has_breakdown(query: dict) -> bool:
        breakdown_filter = query.get("breakdownFilter")
        if not breakdown_filter:
            return False
        if breakdown_filter.get("breakdown_type") and breakdown_filter.get("breakdown"):
            return True
        breakdowns = breakdown_filter.get("breakdowns")
        return isinstance(breakdowns, list) and len(breakdowns) > 0

    @staticmethod
    def _has_compare(query: dict) -> bool:
        compare_filter = query.get("compareFilter")
        if not compare_filter:
            return False
        return compare_filter.get("compare") is True
