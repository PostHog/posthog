"""Contract types for commands.

Other products reach commands through ``api.py``: the GitHub webhook consumer hands over comments,
and the Slack app hands over mentions with the type below.
"""

from posthog.dataclasses import frozen


@frozen
class SlackMention:
    """A Slack message that mentions the PostHog app, as the Slack app hands it over."""

    # The text after the app's own mention, as plain text: links unwrapped to their URLs and
    # Slack's entities decoded.
    text: str
    slack_team_id: str
    slack_user_id: str
    channel: str
    thread_ts: str
    message_ts: str
    # The Slack integration the mention came in on. The answer goes out through it.
    integration_id: int
    integration_team_id: int
    # The PostHog accounts the requester may act as. First the one the Slack app resolved for them,
    # the account its agent acts as: their linked account, else the member of a connected
    # organization with their Slack email. Then every other account linked to their Slack user.
    user_ids: tuple[int, ...]
    # Organizations that connected this Slack workspace. A command reaches only their projects.
    organization_ids: tuple[str, ...]
