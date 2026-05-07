def generate_sql_schema() -> dict:
    return {
        "name": "output_insight_schema",
        "description": "Outputs the final SQL query and the visualization settings that should be used for it",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The SQL query to be executed",
                },
                "display": {
                    "type": "string",
                    "enum": [
                        "ActionsTable",
                        "BoldNumber",
                        "ActionsLineGraph",
                        "ActionsAreaGraph",
                        "ActionsBar",
                        "ActionsStackedBar",
                        "TwoDimensionalHeatmap",
                    ],
                    "description": (
                        "The visualization type for the query results. Use ActionsLineGraph or ActionsAreaGraph for "
                        "time-based data, BoldNumber for a single value, ActionsBar for categorical comparisons, "
                        "ActionsStackedBar when a breakdown column should split bars into series, "
                        "TwoDimensionalHeatmap for x/y/value grids, and ActionsTable only when rows are the intended "
                        "output."
                    ),
                },
                "x_axis": {
                    "type": ["string", "null"],
                    "description": (
                        "Column to use for the x-axis. For time series, this should be the time bucket column. "
                        "Use null for table and single-value displays."
                    ),
                },
                "y_axis": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Numeric result columns to plot as y-axis series. Include only the values that directly "
                        "answer the user's question, not intermediate counts or denominators used to calculate them."
                    ),
                },
                "series_breakdown_column": {
                    "type": ["string", "null"],
                    "description": (
                        "Column that should split one y-axis metric into multiple colored series, such as country, "
                        "browser, model, or plan. Use null when there is no requested breakdown."
                    ),
                },
                "y_axis_format": {
                    "type": ["string", "null"],
                    "enum": ["number", "short", "percent", "none", None],
                    "description": (
                        "Format for the y-axis values. Use percent when the selected y-axis metric is already a "
                        "percentage or rate value intended to display with a percent sign."
                    ),
                },
                "y_axis_decimal_places": {
                    "type": ["integer", "null"],
                    "description": "Decimal places for y-axis values, or null to use the default.",
                },
                "y_axis_prefix": {
                    "type": ["string", "null"],
                    "description": "Prefix for y-axis values, such as a currency symbol. Use null for no prefix.",
                },
                "y_axis_suffix": {
                    "type": ["string", "null"],
                    "description": "Suffix for y-axis values, such as ms, seconds, or %. Use null for no suffix.",
                },
                "show_legend": {
                    "type": "boolean",
                    "description": "Whether the chart should show a legend. Use true for multiple y-axis series or breakdowns.",
                },
            },
            "additionalProperties": False,
            "required": [
                "query",
                "display",
                "x_axis",
                "y_axis",
                "series_breakdown_column",
                "y_axis_format",
                "y_axis_decimal_places",
                "y_axis_prefix",
                "y_axis_suffix",
                "show_legend",
            ],
        },
    }


SQL_SCHEMA = generate_sql_schema()
