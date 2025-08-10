import re
from typing import Any, TypedDict
from urllib.parse import parse_qs, urlparse

import pytest

from posthog.temporal.tests.data_imports.stripe.data import BALANCE_TRANSACTIONS


class StripeData(TypedDict):
    id: str
    created: int


class MockStripeAPI:
    """
    Mock Stripe API.

    Currently only supports balance transactions.

    Can be used to test incremental syncs by setting the `max_created` attribute.
    For example, max_created can be set before initial full sync so that not all data is returned.

    Then, max_created can be reset so that only newer data is returned on incremental syncs.
    """

    def __init__(self, requests_mock):
        self.requests_mock = requests_mock
        self.max_created: int | None = None
        self.requests_mock.get(re.compile(r"https://api\.stripe\.com/v1/.*"), json=self.get_resources)

    def set_max_created(self, max_created: int) -> None:
        self.max_created = max_created

    def reset_max_created(self) -> None:
        self.max_created = None

    def get_resources(self, request: Any, context: Any) -> dict:
        # Get the path without query string, then get the last segment
        resource = urlparse(request.url).path.split("/")[-1]
        data: list[StripeData] = []
        match resource:
            case "balance_transactions":
                data = BALANCE_TRANSACTIONS  # type: ignore
            case _:
                raise ValueError(f"Mock Stripe API: Unknown resource: {resource}")

        # Stripe returns data in reverse chronological order
        filtered_data = sorted(data, key=lambda x: x["created"], reverse=True)

        if self.max_created is not None:
            filtered_data = [tx for tx in filtered_data if tx["created"] <= self.max_created]
        # Handle query params (only those we use are implemented here)
        query = parse_qs(urlparse(request.url).query)
        if "created[gte]" in query:
            created_gte = int(query["created[gte]"][0])
            filtered_data = [tx for tx in filtered_data if tx["created"] >= created_gte]
        elif "created[gt]" in query:
            created_gt = int(query["created[gt]"][0])
            filtered_data = [tx for tx in filtered_data if tx["created"] > created_gt]
        if "created[lte]" in query:
            created_lte = int(query["created[lte]"][0])
            filtered_data = [tx for tx in filtered_data if tx["created"] <= created_lte]
        elif "created[lt]" in query:
            created_lt = int(query["created[lt]"][0])
            filtered_data = [tx for tx in filtered_data if tx["created"] < created_lt]

        if "starting_after" in query:
            starting_after = query["starting_after"][0]
            # find index of starting_after in filtered_data
            starting_after_index = next((i for i, tx in enumerate(filtered_data) if tx["id"] == starting_after), None)
            if starting_after_index is not None:
                filtered_data = filtered_data[starting_after_index + 1 :]

        has_more = False
        if "limit" in query:
            limit = int(query["limit"][0])
            has_more = len(filtered_data) > limit
            filtered_data = filtered_data[:limit]

        return {
            "object": "list",
            "data": filtered_data,
            "has_more": has_more,
            "url": f"/v1/{resource}",
        }

    def get_all_api_calls(self):
        return self.requests_mock.request_history


@pytest.fixture
def mock_stripe_api(requests_mock):
    return MockStripeAPI(requests_mock)
