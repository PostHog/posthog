"""GitHub API integration: artifact download and access-token management."""

from __future__ import annotations

import io
import zipfile

import requests
import structlog

from .models import CIRun, Repo

logger = structlog.get_logger(__name__)


class GitHubIntegrationNotFoundError(Exception):
    pass


def get_github_integration_for_repo(repo: Repo):
    from posthog.models.integration import GitHubIntegration, Integration

    integration = Integration.objects.filter(team_id=repo.team_id, kind="github").first()
    if not integration:
        raise GitHubIntegrationNotFoundError(f"No GitHub integration found for team {repo.team_id}")
    return GitHubIntegration(integration)


def download_run_artifacts(ci_run: CIRun) -> list[bytes]:
    """Download JUnit XML artifacts from a GitHub Actions run."""
    github = get_github_integration_for_repo(ci_run.repo)
    if github.access_token_expired():
        github.refresh_access_token()

    access_token = github.integration.sensitive_config["access_token"]
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    response = requests.get(
        f"https://api.github.com/repos/{ci_run.repo.repo_full_name}/actions/runs/{ci_run.github_run_id}/artifacts",
        headers=headers,
        timeout=30,
    )
    if response.status_code != 200:
        logger.warning(
            "ci_monitoring.artifacts_list_failed",
            status=response.status_code,
            ci_run_id=str(ci_run.id),
        )
        return []

    xml_contents: list[bytes] = []
    for artifact in response.json().get("artifacts", []):
        name = artifact.get("name", "")
        if "junit" not in name.lower():
            continue

        download_url = artifact.get("archive_download_url")
        if not download_url:
            continue

        dl_response = requests.get(download_url, headers=headers, timeout=60)
        if dl_response.status_code != 200:
            logger.warning(
                "ci_monitoring.artifact_download_failed",
                artifact_name=name,
                status=dl_response.status_code,
            )
            continue

        try:
            with zipfile.ZipFile(io.BytesIO(dl_response.content)) as zf:
                for entry in zf.namelist():
                    if entry.endswith(".xml"):
                        xml_contents.append(zf.read(entry))
        except zipfile.BadZipFile:
            logger.warning("ci_monitoring.artifact_bad_zip", artifact_name=name)

    return xml_contents
