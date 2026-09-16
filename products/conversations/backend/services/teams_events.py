"""Bot Framework activities for the SupportHog Microsoft Teams bot.

Two entry points, both reached from the facade after ingress verified the bearer token and
parsed the activity: ``teams_delivery_ownership`` answers which region holds the tenant the
activity is about, and ``accept_teams_event`` runs the certification replies and hands a regular
message to its Celery task. No HTTP in here, because ingress owns the request, the receipt and
the forward to the region that owns the tenant.
"""

from typing import Any, cast

from django.db import OperationalError

import structlog

from posthog.ingress.contracts import DeliveryOwnership, WebhookDelivery
from posthog.ingress.dispatch.database import bounded_statement_timeout, is_statement_timeout

from products.conversations.backend.models import TeamConversationsTeamsConfig
from products.conversations.backend.support_teams import get_bot_from_id, is_trusted_teams_service_url
from products.conversations.backend.tasks.teams import is_duplicate_teams_event, process_teams_event, send_teams_help
from products.conversations.backend.teams import is_bot_added_event, is_command_message

logger = structlog.get_logger(__name__)

# The lookup runs inside the request, before dispatch, so it draws on the delivery's wall clock.
_TENANT_LOOKUP_TIMEOUT_MS = 800


def _activity_tenant_id(activity: dict[str, Any]) -> str:
    return ((activity.get("channelData") or {}).get("tenant") or {}).get("id", "")


def _service_url_is_trusted(delivery: WebhookDelivery) -> bool:
    """Whether the activity's `serviceUrl` is a Microsoft host the bot may send its token to.

    Ingress already proved the issuer signed this exact URL, so `claim_service_url` is the
    activity's own `serviceUrl`. That says the URL is genuine, not that it is one of Microsoft's
    Bot Framework endpoints, and the bot's bearer token goes to whatever this names.
    """
    service_url = delivery.context.get("claim_service_url", "")
    if service_url and not is_trusted_teams_service_url(service_url):
        logger.warning("supporthog_teams_untrusted_service_url", service_url=service_url)
        return False
    return True


def _tenant_is_connected_here(tenant_id: str) -> bool:
    """Whether a team in this region has SupportHog connected for this Teams tenant.

    The Celery task resolves the team again from the tenant id, so nothing here needs the row
    itself. A cancelled statement raises, because a lookup that never finished is not an answer.
    Each caller decides what to do with it.
    """
    with bounded_statement_timeout(_TENANT_LOOKUP_TIMEOUT_MS, models=[TeamConversationsTeamsConfig]):
        return TeamConversationsTeamsConfig.objects.filter(
            teams_tenant_id=tenant_id, teams_graph_access_token__isnull=False
        ).exists()


def teams_delivery_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    """Which region holds the team the delivery's Teams tenant is connected to.

    Two kinds of activity are never forwarded, and answer `UNDECIDED` so they run here exactly
    once. The Teams Store certification requires a reply to a command message such as "help" and
    a proactive welcome when the bot is added, both from a tenant that may never have finished
    OAuth. Neither needs a team, so no region is better placed to answer them, and a forward
    would post the card twice.

    A regular message is the only kind a team answers for. A tenant this region does not know is
    `ELSEWHERE` rather than undecided, so the delivery reaches the other region: it is the only
    one that can tell a tenant it holds from one nobody holds. A lookup that timed out answers
    the same way, for the same reason.
    """
    if not _service_url_is_trusted(delivery):
        # Nothing acts on this activity, here or elsewhere, so there is nothing to forward.
        return DeliveryOwnership.UNDECIDED

    activity: dict[str, Any] = dict(delivery.payload)
    if delivery.event_type != "message" or is_command_message(activity):
        return DeliveryOwnership.UNDECIDED

    tenant_id = _activity_tenant_id(activity)
    if not tenant_id:
        return DeliveryOwnership.UNDECIDED

    try:
        connected_here = _tenant_is_connected_here(tenant_id)
    except OperationalError as error:
        if not is_statement_timeout(error):
            raise
        # Elsewhere rather than an error: the two answers here are "this region owns it" and
        # "somebody else does", and a lookup that never finished has not shown ownership here.
        logger.warning("supporthog_teams_tenant_lookup_timed_out", tenant_id=tenant_id)
        return DeliveryOwnership.ELSEWHERE

    return DeliveryOwnership.LOCAL if connected_here else DeliveryOwnership.ELSEWHERE


def _is_from_the_bot_itself(activity: dict[str, Any]) -> bool:
    """Defense in depth: never reply to a message that claims to come from our own bot identity.

    Bot Framework doesn't echo, but a valid-JWT replay with a spoofed from.id shouldn't loop us.
    """
    try:
        bot_from_id = get_bot_from_id()
    except ValueError:
        return False
    return bool(bot_from_id) and (activity.get("from") or {}).get("id") == bot_from_id


def _accept_conversation_update(activity: dict[str, Any], activity_id: str) -> None:
    """The proactive welcome on install (Teams Store cert 11.4.4.3).

    No PostHog-side team match is needed: the customer hasn't necessarily completed the OAuth
    flow yet, and the welcome card uses only the global Bot Framework token.
    """
    if not is_bot_added_event(activity):
        return
    if activity_id and is_duplicate_teams_event(activity_id):
        return
    cast(Any, send_teams_help).delay(activity=activity, reply=False)


def _accept_message(activity: dict[str, Any], activity_id: str) -> None:
    # Generic-command guarantee (Teams Store cert 11.4.4.3): "Hi", "Hello", "Help", etc. must
    # always get a valid response, even from tenants that haven't completed PostHog OAuth yet
    # (this is exactly the path the AppSource validators run against). Reply with the help card
    # before the team-config gate, then bail without creating a ticket.
    if is_command_message(activity):
        if _is_from_the_bot_itself(activity):
            return
        # A second guard under the ingress dedup mark, which fails open on a cache error: the
        # help card must not be posted twice.
        if activity_id and is_duplicate_teams_event(activity_id):
            return
        cast(Any, send_teams_help).delay(activity=activity, reply=True)
        return

    tenant_id = _activity_tenant_id(activity)
    # Unguarded on purpose: a timed-out lookup fails the delivery, so the dispatcher releases the
    # dedup mark and Bot Framework's redelivery reaches this consumer instead of the activity
    # being lost.
    if not tenant_id or not _tenant_is_connected_here(tenant_id):
        # Quiet on purpose: ingress reports a delivery no region here owns, off the ownership
        # answer this module gave it before dispatch.
        return

    cast(Any, process_teams_event).delay(activity=activity, tenant_id=tenant_id, activity_id=activity_id)


def accept_teams_event(delivery: WebhookDelivery) -> None:
    """Act on one verified Bot Framework activity.

    Ingress refused any activity whose `serviceUrl` the token did not sign, so what is left to
    check is that the URL is a Microsoft host. That runs here as well as in the ownership
    answer, because a consumer must not depend on another lane having run a check for it.
    """
    if not _service_url_is_trusted(delivery):
        return

    activity: dict[str, Any] = dict(delivery.payload)

    activity_id = delivery.delivery_id or ""
    logger.info(
        "supporthog_teams_activity",
        activity_type=delivery.event_type,
        tenant_id=_activity_tenant_id(activity),
    )

    if delivery.event_type == "conversationUpdate":
        _accept_conversation_update(activity, activity_id)
        return
    if delivery.event_type == "message":
        _accept_message(activity, activity_id)
