"""Sends a command's result to where the command came from, once the work it started ends.

The products report the end through their own hook registries, because they cannot import this
product: Stamphog and PostHog Review call a registered callback, and a QA run's save fires the task
run signal. Each callback finds the follow-up the handler saved and queues the message, so the
product's worker never waits on Slack.

This module loads at Django setup, so it imports only the light hook modules.
"""

from typing import Any

from django.db import transaction

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.utils import absolute_uri

from products.review_hog.backend.facade.finished_review_hooks import (
    FinishedReview,
    register_finished_review_hook as register_review_hook,
)
from products.stamphog.backend.facade.finished_review_hooks import (
    FinishedReviewRun,
    register_finished_review_hook as register_stamphog_hook,
)
from products.tasks.backend.facade.task_run_signals import connect_task_run_post_save

from .logic import follow_ups, results


def connect() -> None:
    register_review_hook(on_review_finished)
    register_stamphog_hook(on_stamphog_review_finished)
    connect_task_run_post_save(on_task_run_saved, dispatch_uid="commands_qa_result")


def _deliver(follow_up: follow_ups.FollowUp, message: str) -> None:
    from .tasks.tasks import deliver_follow_up  # noqa: PLC0415 — keeps Celery task modules off the setup import path

    deliver_follow_up.delay(address=dict(follow_up.address), message=message)


def on_review_finished(finished: FinishedReview) -> None:
    project_id = resolve_effective_team_id(finished.team_id)
    key = follow_ups.review_key(project_id, finished.repository, finished.pr_number, finished.review_mode)
    for follow_up in follow_ups.take(key):
        _deliver(follow_up, results.review_result(finished, follow_up))


def on_stamphog_review_finished(finished: FinishedReviewRun) -> None:
    for follow_up in follow_ups.take(follow_ups.stamphog_run_key(str(finished.run_id))):
        _deliver(follow_up, results.stamphog_result(finished, follow_up))


def on_task_run_saved(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    # Every task run save calls this, so the checks that need no query come first.
    if created or not instance.is_terminal:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "status" not in update_fields:
        return
    key = follow_ups.task_run_key(str(instance.id))
    status = str(instance.status)
    task_url = absolute_uri(f"/project/{instance.team_id}/tasks/{instance.task_id}")

    # After the commit, so a rolled-back save takes no follow-up with it.
    def deliver() -> None:
        for follow_up in follow_ups.take(key):
            _deliver(follow_up, results.qa_result(status, task_url, follow_up))

    transaction.on_commit(deliver, robust=True)
