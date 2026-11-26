from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from django.db import transaction

from posthog.api.tagged_item import set_tags_on_object
from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail, Status
from products.conversations.backend.services.messages import TICKET_MESSAGE_SCOPE

if TYPE_CHECKING:
    from posthog.models import Team, User

# The frontend reads this tag to tell a test ticket from a customer's ticket.
SETUP_TEST_TICKET_TAG = "test"

DEFAULT_SETUP_TEST_MESSAGE = (
    "Hi! This is a test ticket. I sent it from the Support setup screen to see how tickets look."
)


def create_setup_test_ticket(*, team: Team, user: User, message: str) -> Ticket:
    """Create a ticket that looks like the team member wrote in as a customer.

    The widget channel stores replies and delivers nothing, so a reply to this ticket
    never leaves PostHog.
    """
    distinct_id = user.distinct_id or str(user.uuid)
    traits = {"email": user.email}
    if user.first_name:
        traits["name"] = user.first_name

    with transaction.atomic():
        ticket = Ticket.objects.create_with_number(
            team=team,
            channel_source=Channel.WIDGET,
            channel_detail=ChannelDetail.WIDGET_API,
            widget_session_id=str(uuid.uuid4()),
            distinct_id=distinct_id,
            status=Status.NEW,
            anonymous_traits=traits,
            unread_team_count=1,
            # No widget request proved who wrote this, so identity stays unknown.
            identity_verified=None,
        )
        Comment.objects.create(
            team=team,
            scope=TICKET_MESSAGE_SCOPE,
            item_id=str(ticket.id),
            content=message,
            item_context={
                "author_type": "customer",
                "distinct_id": distinct_id,
                "distinct_id_verified": False,
                "is_private": False,
            },
        )
        set_tags_on_object([SETUP_TEST_TICKET_TAG], ticket)
    return ticket
