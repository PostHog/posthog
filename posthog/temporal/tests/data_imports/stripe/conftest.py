import re
from urllib.parse import parse_qs, urlparse

import pytest

from posthog.temporal.tests.data_imports.stripe.data import BALANCE_TRANSACTIONS


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
        self.max_created = None
        self.requests_mock.get(re.compile(r"https://api\.stripe\.com/v1/.*"), json=self.get_resources)

    def set_max_created(self, max_created):
        self.max_created = max_created

    def reset_max_created(self):
        self.max_created = None

    def get_resources(self, request, context):
        # Get the path without query string, then get the last segment
        resource = urlparse(request.url).path.split("/")[-1]
        data: list[dict] = []
        match resource:
            case "balance_transactions":
                data = BALANCE_TRANSACTIONS
            case _:
                raise ValueError(f"Mock Stripe API: Unknown resource: {resource}")

        query = parse_qs(urlparse(request.url).query)
        # Stripe returns data in reverse chronological order
        filtered_data = sorted(data, key=lambda x: x["created"], reverse=True)

        if self.max_created:
            filtered_data = [tx for tx in filtered_data if tx["created"] <= self.max_created]

        if "created[gte]" in query:
            created_gte = int(query["created[gte]"][0])
            filtered_data = [tx for tx in filtered_data if tx["created"] >= created_gte]

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

        result = {
            "object": "list",
            "data": filtered_data,
            "has_more": has_more,
            "url": f"/v1/{resource}",
        }

        return result

    def get_all_api_calls(self):
        return self.requests_mock.request_history


@pytest.fixture
def mock_stripe_api(requests_mock):
    # requests_mock.get(re.compile(r"https://api\.stripe\.com/v1/.*"), json=get_resources)
    return MockStripeAPI(requests_mock)
