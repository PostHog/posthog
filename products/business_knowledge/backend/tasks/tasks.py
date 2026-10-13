"""Celery tasks for business_knowledge."""

from celery import shared_task

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.tasks.utils import CeleryQueue

from products.business_knowledge.backend.github_repos import warm_selected_repository


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(GitHubRateLimitError, GitHubIntegrationError, EgressBudgetExhausted),
    retry_backoff=True,
    max_retries=3,
    soft_time_limit=120,
    time_limit=150,
)
def warm_business_knowledge_github_repo(team_id: int, integration_id: int, full_name: str) -> None:
    """Refresh one allowlisted repository's file list. Sheds before live GitHub calls."""
    warm_selected_repository(team_id, integration_id, full_name)
