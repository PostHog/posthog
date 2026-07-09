"""Provision the managed Slack HogFunction behind a Customer analytics event stream.

The stream's delivery is a regular ``template-slack`` real-time destination. Its filters
are rebuilt on every config or membership change: ``(event1 OR event2 …) AND
$group_{account_group_type_index} IN [member account group keys]``. The function is kept
disabled unless the stream is enabled AND has events AND has at least one member with a
group key — so a half-configured stream can never broadcast the whole project's traffic.
"""

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration

from products.cdp.backend.facade.api import HogFunctionSerializer
from products.cdp.backend.facade.models import HogFunction
from products.customer_analytics.backend.models import EventStream, TeamCustomerAnalyticsConfig

if TYPE_CHECKING:
    from posthog.models import Team, User

logger = structlog.get_logger(__name__)


class EventStreamTestMessageError(Exception):
    """The test message could not be sent — unconfigured stream or a Slack API failure."""


_SLACK_TEMPLATE = "template-slack"
_DESTINATION_TYPE = "destination"

# `exact` on an empty list compiles, but an accidental fall-through must never match a real
# group key — pair the disabled state with a filter value no group can have.
_NO_MEMBERS_SENTINEL = "$customer_analytics_event_stream_no_members"


def account_group_type_index(team_id: int) -> int | None:
    """The group type index Customer analytics accounts map onto, or ``None`` when unset."""
    return (
        TeamCustomerAnalyticsConfig.objects.filter(team_id=team_id)
        .values_list("account_group_type_index", flat=True)
        .first()
    )


def member_group_keys(stream: EventStream) -> list[str]:
    """Group keys (``Account.external_id``) of the stream's members. Accounts without an
    external_id have no analytics identity, so they can't be matched to events and are skipped."""
    return sorted(
        stream.members.filter(account__external_id__isnull=False)
        .exclude(account__external_id="")
        .values_list("account__external_id", flat=True)
    )


def _build_filters(stream: EventStream, group_type_index: int, group_keys: list[str]) -> dict[str, Any]:
    return {
        "events": [{"id": name, "type": "events", "order": index} for index, name in enumerate(stream.event_names)],
        "properties": [
            {
                "key": f"$group_{group_type_index}",
                "value": group_keys or [_NO_MEMBERS_SENTINEL],
                "operator": "exact",
                "type": "event",
            }
        ],
    }


def _slack_blocks(group_type_index: int) -> list[dict[str, Any]]:
    group_key_template = f"{{event.properties.$group_{group_type_index}}}"
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*<{person.url}|{person.name}>* triggered *{event.event}*"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Account: {group_key_template}"},
                {"type": "mrkdwn", "text": "Project: <{project.url}|{project.name}>"},
                {"type": "mrkdwn", "text": "<{event.url}|View event>"},
            ],
        },
    ]


def _destination_config(stream: EventStream, group_type_index: int | None, group_keys: list[str]) -> dict[str, Any]:
    channel_display = stream.slack_channel_name or stream.slack_channel_id or "channel"
    enabled = bool(
        stream.enabled
        and stream.event_names
        and group_keys
        and stream.slack_integration_id
        and stream.slack_channel_id
        and group_type_index is not None
    )
    return {
        "type": _DESTINATION_TYPE,
        "enabled": enabled,
        "template_id": _SLACK_TEMPLATE,
        "name": f"Customer analytics event stream → Slack #{channel_display.lstrip('#')}",
        "description": "Streams selected customers' events live to Slack. Managed by Customer analytics.",
        "filters": _build_filters(stream, group_type_index if group_type_index is not None else 0, group_keys),
        "inputs": {
            "slack_workspace": {"value": stream.slack_integration_id},
            "channel": {"value": stream.slack_channel_id},
            "blocks": {"value": _slack_blocks(group_type_index if group_type_index is not None else 0)},
            "text": {"value": "*{person.name}* triggered *{event.event}*"},
        },
    }


def sync_event_stream_destination(stream: EventStream, *, team: "Team", user: "User | None") -> None:
    """Reconcile the stream's managed HogFunction with its current config and membership.

    Creates the function on first sync and updates it in place afterwards, so the CDP
    workers keep a single stable function per stream. A failure propagates — the caller
    runs this inside its write transaction so a stream is never saved pointing at a
    destination that doesn't match it.
    """
    group_type_index = account_group_type_index(team.id)
    group_keys = member_group_keys(stream)
    config = _destination_config(stream, group_type_index, group_keys)

    instance = _managed_hog_function(stream)
    has_slack_config = bool(stream.slack_integration_id and stream.slack_channel_id)
    if not has_slack_config:
        if instance is None:
            # Nothing to provision yet — the template's Slack inputs are required, so the
            # function can only be created once a workspace and channel are configured.
            return
        # Keep the existing (disabled) function's inputs instead of writing null Slack values,
        # which the template's input validation rejects.
        config.pop("inputs")
    context = {
        # HogFunctionSerializer.create() reads context["request"].user for created_by.
        "request": SimpleNamespace(user=user),
        "team_id": team.id,
        "get_team": lambda: team,
        "is_create": instance is None,
    }
    if instance is not None:
        serializer = HogFunctionSerializer(instance, data=config, partial=True, context=context)
    else:
        serializer = HogFunctionSerializer(data=config, context=context)
    serializer.is_valid(raise_exception=True)
    hog_function = serializer.save()
    logger.info(
        "customer_analytics_event_stream_destination_synced",
        team_id=team.id,
        stream_id=str(stream.id),
        hog_function_id=str(hog_function.id),
        created=instance is None,
        enabled=hog_function.enabled,
        member_count=len(group_keys),
    )

    if stream.hog_function_id != hog_function.id:
        stream.hog_function_id = hog_function.id
        stream.save(update_fields=["hog_function_id"])


def sync_event_stream_destination_by_id(*, team: "Team", stream_id: str, user: "User | None") -> None:
    """Load the stream by id and reconcile its destination — the view layer works with
    facade contracts, so it hands over ids rather than model instances."""
    stream = EventStream.objects.for_team(team.id).filter(id=stream_id).first()
    if stream is not None:
        sync_event_stream_destination(stream, team=team, user=user)


def send_test_slack_message(*, team_id: int, stream_id: str, user: "User") -> str | None:
    """Post a test message to the caller's stream's configured Slack channel, mirroring how
    the managed destination delivers. Returns the channel id on success, ``None`` when the
    caller has no such stream; raises :class:`EventStreamTestMessageError` when the stream
    has no Slack config or Slack rejects the message."""
    stream = EventStream.objects.for_team(team_id).filter(id=stream_id, created_by=user).first()
    if stream is None:
        return None
    if not (stream.slack_integration_id and stream.slack_channel_id):
        raise EventStreamTestMessageError("Save a Slack workspace and channel before sending a test message.")
    integration = Integration.objects.filter(team_id=team_id, id=stream.slack_integration_id, kind="slack").first()
    if integration is None:
        raise EventStreamTestMessageError("The stream's Slack workspace is no longer connected.")

    try:
        SlackIntegration(integration).client.chat_postMessage(
            channel=stream.slack_channel_id,
            text=(
                ":wave: This is a test message from PostHog Customer analytics — "
                "your event stream will post matching events to this channel."
            ),
        )
    except SlackApiError as e:
        error = e.response.get("error", "unknown_error") if e.response else "unknown_error"
        logger.warning(
            "customer_analytics_event_stream_test_message_failed",
            team_id=team_id,
            stream_id=str(stream_id),
            error=error,
        )
        hint = " Invite the PostHog bot to the channel and try again." if error == "not_in_channel" else ""
        raise EventStreamTestMessageError(f"Slack rejected the test message: {error}.{hint}")
    return stream.slack_channel_id


def archive_event_stream_destination(stream: EventStream) -> None:
    """Disable and soft-delete the stream's managed HogFunction. Invoked by the EventStream
    ``pre_delete`` signal (signals.py), so it runs on every deletion path."""
    function = _managed_hog_function(stream)
    if function is None:
        return
    function.enabled = False
    function.deleted = True
    # .save() (not .update()) so the post_save signal deregisters the function from the workers.
    function.save()
    logger.info(
        "customer_analytics_event_stream_destination_archived",
        team_id=stream.team_id,
        stream_id=str(stream.id),
        hog_function_id=str(function.id),
    )


def _managed_hog_function(stream: EventStream) -> HogFunction | None:
    if not stream.hog_function_id:
        return None
    return HogFunction.objects.filter(
        team_id=stream.team_id, id=stream.hog_function_id, type=_DESTINATION_TYPE, deleted=False
    ).first()
