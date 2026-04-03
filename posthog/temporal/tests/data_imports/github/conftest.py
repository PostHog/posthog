import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from dateutil import parser as dateutil_parser

from posthog.temporal.tests.data_imports.github.data import COMMITS, ISSUES, PULL_REQUESTS, STARGAZERS


class MockGithubAPI:
    """
    Mock GitHub API.

    Intercepts requests to api.github.com and serves test data with
    support for pagination (Link headers), filtering (since), and sorting.

    Use `set_max_updated` to simulate incremental syncs where only some
    data is visible on the first sync, then call `reset_max_updated` to
    make all data available for subsequent syncs.
    """

    RESOURCES: dict[str, list[dict[str, Any]]] = {
        "issues": ISSUES,
        "pulls": PULL_REQUESTS,
        "commits": COMMITS,
        "stargazers": STARGAZERS,
    }

    def __init__(self, requests_mock):
        self.requests_mock = requests_mock
        self.max_updated: str | None = None
        self.requests_mock.get(re.compile(r"https://api\.github\.com/repos/.*"), json=self.get_resources)

    def set_max_updated(self, max_updated: str) -> None:
        self.max_updated = max_updated

    def reset_max_updated(self) -> None:
        self.max_updated = None

    @staticmethod
    def _get_item_date(item: dict[str, Any]) -> str | None:
        """Extract the relevant date from an item, handling nested commit structure."""
        date_str = item.get("updated_at") or item.get("created_at")
        if not date_str and "commit" in item:
            date_str = item.get("commit", {}).get("author", {}).get("date")
        return date_str

    def get_resources(self, request: Any, context: Any) -> list[dict[str, Any]]:
        path = urlparse(request.url).path
        resource = path.split("/")[-1]

        if resource not in self.RESOURCES:
            context.status_code = 404
            return []

        data = list(self.RESOURCES[resource])

        if self.max_updated is not None:
            max_dt = dateutil_parser.parse(self.max_updated)
            data = [
                item
                for item in data
                if (date_str := self._get_item_date(item)) and dateutil_parser.parse(date_str) <= max_dt
            ]

        query = parse_qs(urlparse(request.url).query)

        if "since" in query:
            since_dt = dateutil_parser.parse(query["since"][0])
            data = [
                item
                for item in data
                if (date_str := self._get_item_date(item)) and dateutil_parser.parse(date_str) > since_dt
            ]

        sort_field = query.get("sort", [None])[0]
        direction = query.get("direction", ["asc"])[0]
        if sort_field:
            sort_key = f"{sort_field}_at" if not sort_field.endswith("_at") else sort_field
            data = sorted(
                data,
                key=lambda x: x.get(sort_key) or self._get_item_date(x) or "",
                reverse=(direction == "desc"),
            )

        per_page = int(query.get("per_page", ["100"])[0])
        page = int(query.get("page", ["1"])[0])
        start = (page - 1) * per_page
        end = start + per_page

        has_more = end < len(data)
        data = data[start:end]

        if has_more:
            base_url = request.url.split("?")[0]
            next_page = page + 1
            context.headers["Link"] = f'<{base_url}?page={next_page}&per_page={per_page}>; rel="next"'

        return data

    def get_all_api_calls(self) -> list:
        return self.requests_mock.request_history


@pytest.fixture
def mock_github_api(requests_mock):
    return MockGithubAPI(requests_mock)
