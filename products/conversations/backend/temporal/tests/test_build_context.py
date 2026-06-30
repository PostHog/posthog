from __future__ import annotations

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team

from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.temporal.ai_reply.activities.build_context import _build_context_sync


@pytest.mark.django_db
@patch(
    "products.conversations.backend.temporal.ai_reply.activities.build_context.team_github_repo_accessible",
    return_value=False,
)
@patch(
    "products.conversations.backend.temporal.ai_reply.activities.build_context.team_github_integration_present",
    return_value=True,
)
def test_build_context_clears_inaccessible_bug_fix_repo(
    _mock_integration_present,
    _mock_repo_accessible,
) -> None:
    org = Organization.objects.create(name="bugfix-org")
    team = Team.objects.create(organization=org, name="bugfix-team")
    team.conversations_settings = {
        "ai_bug_fix_prs_enabled": True,
        "ai_bug_fix_repo": "posthog/posthog",
    }
    team.save()
    ticket = Ticket.objects.create_with_number(
        team=team,
        widget_session_id="bugfix-session",
        distinct_id="bugfix-distinct",
    )

    output = _build_context_sync(team.id, str(ticket.id))

    assert output.bug_fix_enabled is True
    assert output.github_integration_present is True
    assert output.bug_fix_repo is None
