"""Activity-log integration for agent_stack.

Wires `model_activity_signal` receivers for `AgentApplication` and
`AgentRevision`. Both models mix `ModelActivityMixin` in `models.py`, so
every save fires this handler with `before_update` / `after_update`
populated; we forward to `log_activity` with the standard
`changes_between` diff.

Receivers are imported in `apps.AgentStackConfig.ready()` so they bind
once at Django startup.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import AnonymousUser

from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from .models import AgentApplication, AgentRevision


@mutable_receiver(model_activity_signal, sender=AgentApplication)
def handle_agent_application_change(
    sender: type[AgentApplication],
    scope: str,
    before_update: AgentApplication | None,
    after_update: AgentApplication | None,
    activity: str,
    user: User | AnonymousUser | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    application = after_update or before_update
    if application is None:
        return

    log_activity(
        organization_id=application.team.organization_id,
        team_id=application.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=application.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=application.slug,
        ),
    )


@mutable_receiver(model_activity_signal, sender=AgentRevision)
def handle_agent_revision_change(
    sender: type[AgentRevision],
    scope: str,
    before_update: AgentRevision | None,
    after_update: AgentRevision | None,
    activity: str,
    user: User | AnonymousUser | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    revision = after_update or before_update
    if revision is None:
        return

    application = revision.application
    # Display name: `<slug>@<short-id> (<state>)` matches the model's __str__.
    short_id = str(revision.id)[:8]
    name = f"{application.slug}@{short_id} ({revision.state})"

    log_activity(
        organization_id=application.team.organization_id,
        team_id=application.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=revision.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=name,
        ),
    )
