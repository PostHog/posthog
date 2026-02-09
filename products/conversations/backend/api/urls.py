"""URL configuration for Conversations widget API."""

from django.urls import path, re_path

from .slack_channels import SlackChannelsView
from .slack_events import supporthog_event_handler
from .widget import WidgetMarkReadView, WidgetMessagesView, WidgetMessageView, WidgetTicketsView

urlpatterns = [
    path("v1/widget/message", WidgetMessageView.as_view(), name="widget-message-v1"),
    path("v1/widget/messages/<uuid:ticket_id>", WidgetMessagesView.as_view(), name="widget-messages-v1"),
    path("v1/widget/messages/<uuid:ticket_id>/read", WidgetMarkReadView.as_view(), name="widget-mark-read-v1"),
    path("v1/widget/tickets", WidgetTicketsView.as_view(), name="widget-tickets-v1"),
    # SupportHog Slack app events (public, no auth)
    path("v1/slack/events", supporthog_event_handler, name="supporthog-slack-events"),
    # Slack channels (authenticated, optional trailing slash)
    re_path(r"^v1/slack/channels/?$", SlackChannelsView.as_view(), name="slack-channels"),
]
