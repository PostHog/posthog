"""
Utility functions for LLMA daily metrics aggregation.
"""

from pathlib import Path

from jinja2 import Template

from dags.llma.daily_metrics.config import config

# SQL template directory
SQL_DIR = Path(__file__).parent / "sql"

# Metric types to include (matches SQL filenames without .sql extension)
# Set to None to include all, or list specific ones to include
ENABLED_METRICS: list[str] | None = None  # or ["event_counts", "error_rates"]


def get_llma_events_cte(date_start: str, date_end: str) -> str:
    """
    Generate CTE that pre-filters events to only LLMA teams and event types.

    This two-step approach (first find teams, then filter events) allows ClickHouse
    to use the sorting key (team_id, timestamp) more efficiently.
    """
    event_types_sql = ", ".join(f"'{et}'" for et in config.ai_event_types)
    return f"""teams_with_ai_events AS (
    SELECT DISTINCT team_id
    FROM events
    WHERE event IN ({event_types_sql})
      AND timestamp >= toDateTime('{date_start}', 'UTC')
      AND timestamp < toDateTime('{date_end}', 'UTC')
),
llma_events AS (
    SELECT *
    FROM events
    WHERE team_id IN (SELECT team_id FROM teams_with_ai_events)
      AND event IN ({event_types_sql})
      AND timestamp >= toDateTime('{date_start}', 'UTC')
      AND timestamp < toDateTime('{date_end}', 'UTC')
)"""


def get_insert_query(date_start: str, date_end: str) -> str:
    """
    Generate SQL to aggregate AI event counts by team and metric type.

    Uses long format: each metric_name is a separate row for easy schema evolution.
    Automatically discovers and combines all SQL templates in the sql/ directory.

    To add a new metric type, simply add a new .sql file in dags/llma/sql/.
    Each SQL file should return columns: date, team_id, metric_name, metric_value
    """
    # Discover all SQL template files
    sql_files = sorted(SQL_DIR.glob("*.sql"))

    # Filter by enabled metrics if specified
    if ENABLED_METRICS is not None:
        sql_files = [f for f in sql_files if f.stem in ENABLED_METRICS]

    if not sql_files:
        raise ValueError(f"No SQL template files found in {SQL_DIR}")

    # Load and render each template
    rendered_queries = []
    template_context = {
        "event_types": config.ai_event_types,
        "pageview_mappings": config.pageview_mappings,
        "date_start": date_start,
        "date_end": date_end,
        "include_error_rates": config.include_error_rates,
    }

    for sql_file in sql_files:
        with open(sql_file) as f:
            template = Template(f.read())
            rendered = template.render(**template_context)
            if rendered.strip():  # Only include non-empty queries
                rendered_queries.append(rendered)

    # Combine all queries with UNION ALL
    combined_query = "\n\nUNION ALL\n\n".join(rendered_queries)

    # Generate the llma_events CTE
    llma_events_cte = get_llma_events_cte(date_start, date_end)

    # Wrap in INSERT INTO statement with CTE
    return f"""INSERT INTO {config.table_name} (date, team_id, metric_name, metric_value)

WITH {llma_events_cte}

{combined_query}"""


def get_delete_query(date_start: str, date_end: str) -> str:
    """Generate SQL to delete existing data for the date range."""
    return f"ALTER TABLE {config.table_name} DELETE WHERE date >= '{date_start}' AND date < '{date_end}'"
