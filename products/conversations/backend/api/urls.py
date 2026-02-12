"""URL configuration for Conversations widget and external API."""

from django.urls import path, re_path

from .external import ExternalTicketView
from .slack_channels import SlackChannelsView
from .slack_events import supporthog_event_handler
from .slack_oauth import SupportSlackAuthorizeView, support_slack_oauth_callback
from .widget import WidgetMarkReadView, WidgetMessagesView, WidgetMessageView, WidgetTicketsView

urlpatterns = [
    path("v1/widget/message", WidgetMessageView.as_view(), name="widget-message-v1"),
    path("v1/widget/messages/<uuid:ticket_id>", WidgetMessagesView.as_view(), name="widget-messages-v1"),
    path("v1/widget/messages/<uuid:ticket_id>/read", WidgetMarkReadView.as_view(), name="widget-mark-read-v1"),
    path("v1/widget/tickets", WidgetTicketsView.as_view(), name="widget-tickets-v1"),
    # SupportHog Slack app events (public, no auth)
    path("v1/slack/events", supporthog_event_handler, name="supporthog-slack-events"),
    path("v1/slack/authorize", SupportSlackAuthorizeView.as_view(), name="supporthog-slack-authorize"),
    path("v1/slack/callback", support_slack_oauth_callback, name="supporthog-slack-callback"),
    # Slack channels (authenticated, optional trailing slash)
    re_path(r"^v1/slack/channels/?$", SlackChannelsView.as_view(), name="slack-channels"),
    path("external/ticket/<uuid:ticket_id>", ExternalTicketView.as_view(), name="external-ticket"),
]
