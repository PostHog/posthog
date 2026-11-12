"""Kept free of Django imports so the command grammar can load it before Django is set up."""

from posthog.dataclasses import frozen


@frozen
class ProjectMember:
    """A project the requester may act in, and the requester's PostHog account that acts there."""

    team_id: int
    user_id: int
