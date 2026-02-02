"""Utility functions for ingestion acceptance tests."""


def mask_key_value(value: str) -> str:
    """Turn 'phx_123456abcd' into 'phx_...abcd'."""
    if len(value) < 16:
        return "********"
    return f"{value[:4]}...{value[-4:]}"
