from typing import cast, Union
from datetime import datetime, UTC

from posthog.hogql import ast


class WebAnalyticsPreAggregatedQueryBuilder:
    def __init__(self, runner, supported_props_filters) -> None:
        self.runner = runner
        self.supported_props_filters = supported_props_filters

    def can_use_preaggregated_tables(self) -> bool:
        query = self.runner.query

        for prop in query.properties:
            if hasattr(prop, "key") and prop.key not in self.supported_props_filters:
                return False

        if query.conversionGoal:
            return False

        # Only work for fixed-dates that don't include current-date in the filters while we test the pre-aggregated tables
        today = datetime.now(UTC).date()
        if self.runner.query_date_range.date_to().date() >= today:
            return False

        return True

    # We can probably use the hogql general filters somehow but it was not working by default and it was a lot of moving parts to debug at once so
    # TODO: come back to this later to make sure we're not overcomplicating things
    def _get_filters(self, table_name: str):
        current_date_expr = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=[table_name, "day_bucket"]),
                    right=ast.Constant(
                        value=(
                            self.runner.query_compare_to_date_range.date_from()
                            if self.runner.query_compare_to_date_range
                            else self.runner.query_date_range.date_from()
                        )
                    ),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=[table_name, "day_bucket"]),
                    right=ast.Constant(value=self.runner.query_date_range.date_to()),
                ),
            ]
        )

        filter_parts: list[Union[ast.And, ast.CompareOperation]] = [current_date_expr]

        for posthog_field, table_field in self.supported_props_filters.items():
            for prop in self.runner.query.properties:
                if hasattr(prop, "key") and prop.key == posthog_field and hasattr(prop, "value"):
                    value = prop.value

                    if value is not None and hasattr(value, "id"):
                        value = value.id

                    # The device_type input differs between "Desktop" | ["Mobile", "Tablet"]
                    if isinstance(value, list):
                        values = [v.id if v is not None and hasattr(v, "id") else v for v in value]
                        filter_expr = ast.CompareOperation(
                            op=ast.CompareOperationOp.In,
                            left=ast.Field(chain=[table_name, table_field]),
                            right=ast.Tuple(exprs=[ast.Constant(value=v) for v in values]),
                        )

                        filter_parts.append(filter_expr)
                    else:
                        filter_expr = ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=[table_name, table_field]),
                            right=ast.Constant(value=value),
                        )

                        filter_parts.append(filter_expr)

        if len(filter_parts) > 1:
            return ast.Call(name="and", args=cast(list[ast.Expr], filter_parts))
        elif len(filter_parts) == 1:
            return filter_parts[0]

        return None

    def get_date_ranges(self) -> tuple[str, str]:
        current_date_from = self.runner.query_date_range.date_from_str
        current_date_to = self.runner.query_date_range.date_to_str

        if self.runner.query_compare_to_date_range:
            previous_date_from = self.runner.query_compare_to_date_range.date_from_str
            previous_date_to = self.runner.query_compare_to_date_range.date_to_str
        else:
            # If we don't have a previous period, we can just use the same data as the values won't be used
            # and our query stays simpler.
            # TODO: Make sure the frontend handles this correctly for every case
            previous_date_from = current_date_from
            previous_date_to = current_date_to

        current_period_filter = f"day_bucket >= '{current_date_from}' AND day_bucket <= '{current_date_to}'"
        previous_period_filter = f"day_bucket >= '{previous_date_from}' AND day_bucket <= '{previous_date_to}'"

        return (previous_period_filter, current_period_filter)
