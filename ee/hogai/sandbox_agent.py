from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog
import posthoganalytics

from posthog.models import Team, User

from products.tasks.backend.models import Task, TaskRun

if TYPE_CHECKING:
    from products.slack_app.backend.slack_thread import SlackThreadContext

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SandboxAgentTaskResult:
    task_id: UUID
    run_id: UUID
    workflow_id: str


class FeatureNotEnabledError(Exception):
    pass


class SandboxAgentService:
    """Entry point for spawning background AI agents via sandbox tasks."""

    @staticmethod
    def spawn_sandbox_task(
        *,
        team: Team,
        user: User,
        title: str,
        description: str,
        origin_product: str,
        repository: str | None = None,
        create_pr: bool = True,
        slack_thread_context: SlackThreadContext | None = None,
        slack_thread_url: str | None = None,
        output_schema: dict | None = None,
    ) -> SandboxAgentTaskResult:
        """Spawn a sandbox task (behind `tasks` feature flag).

        Delegates to Task.create_and_run() after checking the feature flag.
        """

        tasks_enabled = posthoganalytics.feature_enabled(
            "tasks",
            user.distinct_id or "",
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

        if not tasks_enabled:
            raise FeatureNotEnabledError("The 'tasks' feature is not enabled for this user/organization")

        task = Task.create_and_run(
            team=team,
            title=title,
            description=description,
            origin_product=Task.OriginProduct(origin_product),
            user_id=user.id,
            repository=repository,
            create_pr=create_pr,
            slack_thread_context=slack_thread_context,
            slack_thread_url=slack_thread_url,
            output_schema=output_schema,
        )

        latest_run = task.latest_run
        run_id = latest_run.id if latest_run else uuid4()
        workflow_id = TaskRun.get_workflow_id(str(task.id), str(run_id))

        logger.info(
            "sandbox_task_spawned",
            task_id=str(task.id),
            run_id=str(run_id),
            workflow_id=workflow_id,
            team_id=team.id,
        )

        return SandboxAgentTaskResult(
            task_id=task.id,
            run_id=run_id,
            workflow_id=workflow_id,
        )
