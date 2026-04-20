"""Shared fixtures for ci_monitoring tests."""

import hmac
import json
import hashlib

import pytest
from unittest.mock import MagicMock

from products.ci_monitoring.backend.models import CIRun, Repo


@pytest.fixture
def repo(team):
    return Repo.objects.create(
        team=team,
        repo_external_id=12345,
        repo_full_name="test-org/test-repo",
        default_branch="main",
    )


@pytest.fixture
def ci_run(repo):
    from django.utils import timezone

    return CIRun.objects.create(
        team_id=repo.team_id,
        repo=repo,
        github_run_id=99999,
        workflow_name="CI Backend",
        commit_sha="abc123def456",
        branch="main",
        conclusion="success",
        started_at=timezone.now(),
        completed_at=timezone.now(),
    )


@pytest.fixture
def mock_github_integration(team, mocker):
    from posthog.models.integration import GitHubIntegration, Integration

    mock_integration = MagicMock(spec=Integration)
    mock_integration.id = 1
    mock_integration.team_id = team.id
    mock_integration.kind = "github"
    mock_integration.sensitive_config = {
        "access_token": "ghs_fake_token",
    }

    original_filter = Integration.objects.filter

    def patched_filter(*args, **kwargs):
        if kwargs.get("kind") == "github" and kwargs.get("team_id") == team.id:
            mock_qs = MagicMock()
            mock_qs.first.return_value = mock_integration
            return mock_qs
        return original_filter(*args, **kwargs)

    mocker.patch.object(Integration.objects, "filter", side_effect=patched_filter)
    mocker.patch.object(GitHubIntegration, "access_token_expired", return_value=False)

    return mock_integration


WEBHOOK_SECRET = "test-webhook-secret"


def make_webhook_payload(
    *,
    repo_external_id: int = 12345,
    repo_full_name: str = "test-org/test-repo",
    run_id: int = 99999,
    workflow_name: str = "CI Backend",
    head_sha: str = "abc123",
    head_branch: str = "main",
    conclusion: str = "success",
    action: str = "completed",
    pr_number: int | None = None,
) -> dict:
    pull_requests = [{"number": pr_number}] if pr_number else []
    return {
        "action": action,
        "workflow_run": {
            "id": run_id,
            "name": workflow_name,
            "head_sha": head_sha,
            "head_branch": head_branch,
            "conclusion": conclusion,
            "run_started_at": "2026-03-20T10:00:00Z",
            "updated_at": "2026-03-20T10:05:00Z",
            "pull_requests": pull_requests,
        },
        "repository": {
            "id": repo_external_id,
            "full_name": repo_full_name,
        },
    }


def sign_payload(payload: dict, secret: str = WEBHOOK_SECRET) -> str:
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={signature}"
