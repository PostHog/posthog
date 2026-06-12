"""Shared dataclasses for PostHog Slack App Temporal workflows.

Living here (and not in the workflow module) so activities split into this
package can take the inputs dataclass as their typed signature without
creating an import cycle with the workflow module.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class PostHogCodeSlackMentionWorkflowInputs:
    event: dict[str, Any]
    integration_id: int
    slack_team_id: str
    # Event that dispatched the workflow
    slack_event_id: str | None = None
    # Resolved at routing time. ``None`` only on in-flight workflow histories
    # started before this field existed; those fall back to the in-workflow
    # resolve activity below. Remove the fallback (and this field's optionality)
    # once the workflow history retention window has elapsed.
    user_id: int | None = None
    # True when the workflow was started for an untagged thread reply (event type
    # ``message``) rather than an explicit ``app_mention``. The routing layer
    # already verified a ``SlackThreadTaskMapping`` exists before dispatch, but
    # if the mapping is gone by the time the followup activity runs (race with
    # cleanup), we must NOT fall through to the new-task path — the user never
    # tagged us, so kicking off a brand-new agent run would be wrong.
    untagged_followup: bool = False
