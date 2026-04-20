"""Celery tasks for ci_monitoring."""

import uuid

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def ingest_ci_run_artifacts(*, ci_run_id: str) -> None:
    """Download and parse test artifacts for a CI run."""
    from .. import logic
    from ..ingestion import parse_junit_xml
    from ..models import CIRun

    ci_run = CIRun.objects.select_related("repo").get(id=ci_run_id)

    try:
        xml_contents = logic.download_run_artifacts(ci_run)
    except Exception:
        logger.exception("ci_monitoring.artifact_download_failed", ci_run_id=ci_run_id)
        return

    if not xml_contents:
        logger.info("ci_monitoring.no_artifacts", ci_run_id=ci_run_id)
        ci_run.artifacts_ingested = True
        ci_run.save(update_fields=["artifacts_ingested"])
        return

    all_results = []
    for xml_content in xml_contents:
        all_results.extend(parse_junit_xml(xml_content))

    logic.ingest_test_results(ci_run=ci_run, parsed_results=all_results)

    # Update streak if this is a default branch run
    if ci_run.branch == ci_run.repo.default_branch:
        logic.record_main_branch_run(
            repo_id=ci_run.repo_id,
            team_id=ci_run.team_id,
            conclusion=ci_run.conclusion,
            workflow_name=ci_run.workflow_name,
        )

    # Recompute flake scores
    logic.update_flake_scores(repo_id=ci_run.repo_id, team_id=ci_run.team_id)

    logger.info(
        "ci_monitoring.ingestion_complete",
        ci_run_id=ci_run_id,
        total_tests=ci_run.total_tests,
        flaky=ci_run.flaky,
    )


@shared_task(ignore_result=True)
def create_quarantine_github_issue(*, quarantine_id: str) -> None:
    """Create a GitHub issue for a quarantined test."""
    # Phase 4
    pass


@shared_task(ignore_result=True)
def update_flake_scores(*, repo_id: str, team_id: int) -> None:
    """Recompute rolling 30-day flake scores for all tests in a repo."""
    from .. import logic

    logic.update_flake_scores(repo_id=uuid.UUID(repo_id), team_id=team_id)
