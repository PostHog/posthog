import base64
from collections.abc import Iterator
from typing import Any

import requests
from structlog.typing import FilteringBoundLogger


class JiraAPIError(Exception):
    """Exception raised for Jira API errors"""

    pass


class JiraClient:
    """Client for interacting with the Jira REST API"""

    def __init__(self, domain: str, email: str, api_token: str, logger: FilteringBoundLogger):
        self.domain = domain.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.logger = logger
        self.base_url = f"https://{self.domain}/rest/api/3"

        # Create Basic Auth header
        credentials = f"{email}:{api_token}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _make_request(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a request to the Jira API"""
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise JiraAPIError("Invalid credentials: Unauthorized") from e
            elif e.response.status_code == 403:
                raise JiraAPIError("Access forbidden: Check API token permissions") from e
            elif e.response.status_code == 404:
                raise JiraAPIError(f"Resource not found: {url}") from e
            else:
                raise JiraAPIError(f"HTTP error {e.response.status_code}: {e.response.text}") from e
        except requests.exceptions.RequestException as e:
            raise JiraAPIError(f"Request failed: {str(e)}") from e

    def test_connection(self) -> bool:
        """Test the connection to Jira API"""
        try:
            url = f"{self.base_url}/myself"
            self._make_request(url)
            return True
        except JiraAPIError:
            return False

    def get_issues(
        self,
        incremental_value: str | None = None,
        page_size: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """Fetch issues from Jira using JQL search"""
        start_at = 0

        # Build JQL query for incremental sync
        jql_parts = []
        if incremental_value:
            # Convert incremental value to Jira datetime format
            jql_parts.append(f"updated >= '{incremental_value}'")

        jql = " AND ".join(jql_parts) if jql_parts else ""

        while True:
            url = f"{self.base_url}/search"
            params = {
                "jql": jql,
                "maxResults": page_size,
                "startAt": start_at,
                "fields": "*all",
                "expand": "changelog,renderedFields",
            }

            response = self._make_request(url, params)
            issues = response.get("issues", [])

            if not issues:
                break

            yield from issues

            # Check if there are more results
            total = response.get("total", 0)
            start_at += page_size

            if start_at >= total:
                break

    def get_projects(self, page_size: int = 50) -> Iterator[dict[str, Any]]:
        """Fetch all projects"""
        start_at = 0

        while True:
            url = f"{self.base_url}/project/search"
            params = {
                "maxResults": page_size,
                "startAt": start_at,
                "expand": "description,lead,issueTypes,url,projectKeys",
            }

            response = self._make_request(url, params)
            projects = response.get("values", [])

            if not projects:
                break

            yield from projects

            # Check if there are more results
            if response.get("isLast", True):
                break

            start_at += page_size

    def get_users(self, page_size: int = 50) -> Iterator[dict[str, Any]]:
        """Fetch all users"""
        start_at = 0

        while True:
            url = f"{self.base_url}/users/search"
            params = {
                "maxResults": page_size,
                "startAt": start_at,
            }

            response = self._make_request(url, params)

            if not response:
                break

            yield from response

            # Check if there are more results
            if len(response) < page_size:
                break

            start_at += page_size

    def get_issue_comments(
        self,
        incremental_value: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Fetch comments from all issues"""
        # First get all issues
        for issue in self.get_issues():
            issue_key = issue.get("key")
            issue_id = issue.get("id")

            # Get comments for this issue
            start_at = 0
            page_size = 100

            while True:
                url = f"{self.base_url}/issue/{issue_key}/comment"
                params = {
                    "maxResults": page_size,
                    "startAt": start_at,
                }

                response = self._make_request(url, params)
                comments = response.get("comments", [])

                if not comments:
                    break

                for comment in comments:
                    # Add issue context to comment
                    comment["issue_id"] = issue_id
                    comment["issue_key"] = issue_key

                    # Filter by incremental value if provided
                    if incremental_value:
                        comment_updated = comment.get("updated")
                        if comment_updated and comment_updated < incremental_value:
                            continue

                    yield comment

                # Check if there are more results
                total = response.get("total", 0)
                start_at += page_size

                if start_at >= total:
                    break

    def get_boards(self, page_size: int = 50) -> Iterator[dict[str, Any]]:
        """Fetch all boards"""
        start_at = 0

        while True:
            url = f"{self.base_url}/board"
            params = {
                "maxResults": page_size,
                "startAt": start_at,
            }

            try:
                response = self._make_request(url, params)
                boards = response.get("values", [])

                if not boards:
                    break

                yield from boards

                # Check if there are more results
                if response.get("isLast", True):
                    break

                start_at += page_size
            except JiraAPIError as e:
                # Boards endpoint might not be available for all Jira instances
                self.logger.warning(f"Could not fetch boards: {str(e)}")
                break

    def get_sprints(self) -> Iterator[dict[str, Any]]:
        """Fetch sprints from all boards"""
        for board in self.get_boards():
            board_id = board.get("id")
            start_at = 0
            page_size = 50

            while True:
                url = f"{self.base_url}/board/{board_id}/sprint"
                params = {
                    "maxResults": page_size,
                    "startAt": start_at,
                }

                try:
                    response = self._make_request(url, params)
                    sprints = response.get("values", [])

                    if not sprints:
                        break

                    for sprint in sprints:
                        # Add board context to sprint
                        sprint["board_id"] = board_id
                        yield sprint

                    # Check if there are more results
                    if response.get("isLast", True):
                        break

                    start_at += page_size
                except JiraAPIError as e:
                    self.logger.warning(f"Could not fetch sprints for board {board_id}: {str(e)}")
                    break

    def get_components(self) -> Iterator[dict[str, Any]]:
        """Fetch components from all projects"""
        for project in self.get_projects():
            project_key = project.get("key")

            try:
                url = f"{self.base_url}/project/{project_key}/components"
                response = self._make_request(url)

                for component in response:
                    # Add project context to component
                    component["project_key"] = project_key
                    component["project_id"] = project.get("id")
                    yield component
            except JiraAPIError as e:
                self.logger.warning(f"Could not fetch components for project {project_key}: {str(e)}")
                continue

    def get_worklogs(
        self,
        incremental_value: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Fetch worklogs from all issues"""
        # First get all issues
        for issue in self.get_issues():
            issue_key = issue.get("key")
            issue_id = issue.get("id")

            try:
                url = f"{self.base_url}/issue/{issue_key}/worklog"
                response = self._make_request(url)
                worklogs = response.get("worklogs", [])

                for worklog in worklogs:
                    # Add issue context to worklog
                    worklog["issue_id"] = issue_id
                    worklog["issue_key"] = issue_key

                    # Filter by incremental value if provided
                    if incremental_value:
                        worklog_updated = worklog.get("updated")
                        if worklog_updated and worklog_updated < incremental_value:
                            continue

                    yield worklog
            except JiraAPIError as e:
                self.logger.warning(f"Could not fetch worklogs for issue {issue_key}: {str(e)}")
                continue


def validate_credentials(domain: str, email: str, api_token: str, logger: FilteringBoundLogger) -> bool:
    """Validate Jira credentials"""
    client = JiraClient(domain, email, api_token, logger)
    return client.test_connection()
