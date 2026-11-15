"""People an integration can assign an external issue to, shared by the issue tracker integrations."""

from posthog.dataclasses import frozen

MAX_ASSIGNEES = 100


@frozen
class Assignee:
    # Linear user ID, GitHub login, GitLab user ID, or Jira account ID: whatever the provider's create call takes.
    id: str
    name: str


class AssigneeLookupFailed(Exception):
    """The provider could not list assignable users."""


class ReconnectRequired(Exception):
    """The connection's grant predates a scope that the call needs, so only a reconnect fixes it."""
