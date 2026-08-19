"""GitLab integration."""

import requests

from posthog.security.url_validation import is_url_allowed

from . import common, model


class GitLabIntegrationError(Exception):
    pass


class GitLabIntegration:
    integration: model.Integration

    @staticmethod
    def get(hostname: str, endpoint: str, project_access_token: str) -> dict:
        url = f"{hostname}/api/v4/{endpoint}"
        allowed, error = is_url_allowed(url)
        if not allowed:
            raise GitLabIntegrationError(f"Invalid GitLab hostname: {error}")

        response = requests.get(
            url,
            headers={"PRIVATE-TOKEN": project_access_token},
            # disallow redirects to prevent SSRF on redirected host
            allow_redirects=False,
            timeout=10,
        )

        return response.json()

    @staticmethod
    def post(hostname: str, endpoint: str, project_access_token: str, json: dict) -> dict:
        url = f"{hostname}/api/v4/{endpoint}"
        allowed, error = is_url_allowed(url)
        if not allowed:
            raise GitLabIntegrationError(f"Invalid GitLab hostname: {error}")

        response = requests.post(
            url,
            json=json,
            headers={"PRIVATE-TOKEN": project_access_token},
            # disallow redirects to prevent SSRF on redirected host
            allow_redirects=False,
            timeout=10,
        )

        return response.json()

    @classmethod
    def create_integration(cls, hostname, project_id, project_access_token, team_id, user) -> model.Integration:
        project = cls.get(hostname, f"projects/{project_id}", project_access_token)

        integration = model.Integration.objects.create(
            team_id=team_id,
            kind=model.Integration.IntegrationKind.GITLAB,
            integration_id=project.get("name_with_namespace"),
            config={
                "hostname": hostname,
                "path_with_namespace": project.get("path_with_namespace"),
                "project_id": project.get("id"),
            },
            sensitive_config={"access_token": project_access_token},
            created_by=user,
        )

        return integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "gitlab":
            raise Exception("GitLabIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @property
    def project_path(self) -> str:
        return common.dot_get(self.integration.config, "path_with_namespace")

    @property
    def hostname(self) -> str:
        return common.dot_get(self.integration.config, "hostname")

    def create_issue(self, config: dict[str, str]):
        title: str = config.pop("title")
        description: str = config.pop("body")

        hostname = self.integration.config.get("hostname")
        project_id = self.integration.config.get("project_id")
        access_token = self.integration.sensitive_config.get("access_token")

        issue = GitLabIntegration.post(
            hostname,
            f"projects/{project_id}/issues",
            access_token,
            {
                "title": title,
                "description": description,
                "labels": "posthog",
            },
        )

        return {"issue_id": issue["iid"]}
