"""Utility functions for trace summarization."""

from datetime import datetime


def format_datetime_for_clickhouse(iso_string: str) -> str:
    """Convert ISO format datetime string to ClickHouse-compatible format."""
    dt = datetime.fromisoformat(iso_string)
    return dt.strftime("%Y-%m-%d %H:%M:%S")
