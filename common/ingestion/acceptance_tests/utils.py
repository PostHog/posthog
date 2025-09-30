"""Utilities for acceptance tests."""

import os


def get_service_url(service: str = "proxy") -> str:
    """Get the URL for a service."""
    if base_url := os.environ.get("POSTHOG_TEST_BASE_URL"):
        return base_url

    service_urls = {
        "proxy": "http://localhost:8010",
        "s3": "http://localhost:19000",
        "clickhouse": "http://localhost:8123",
    }

    return service_urls.get(service, "http://localhost:8010")
