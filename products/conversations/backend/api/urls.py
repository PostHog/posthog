"""URL configuration for Conversations widget and external API."""

from django.urls import path, re_path

from .email_events import email_inbound_handler
from .email_settings import EmailConnectView, EmailDisconnectView, EmailStatusView
from .external import ExternalTicketView
from .restore import WidgetRestoreRedeemView, WidgetRestoreRequestView
from .slack_channels import SlackChannelsView
from .slack_events import supporthog_event_handler
from .slack_oauth import SupportSlackAuthorizeView, SupportSlackDisconnectView, support_slack_oauth_callback
from .widget import WidgetMarkReadView, WidgetMessagesView, WidgetMessageView, WidgetTicketsView

urlpatterns = [
    path("v1/widget/message", WidgetMessageView.as_view(), name="widget-message-v1"),
    path("v1/widget/messages/<uuid:ticket_id>", WidgetMessagesView.as_view(), name="widget-messages-v1"),
    path("v1/widget/messages/<uuid:ticket_id>/read", WidgetMarkReadView.as_view(), name="widget-mark-read-v1"),
    path("v1/widget/tickets", WidgetTicketsView.as_view(), name="widget-tickets-v1"),
    path("v1/widget/restore/request", WidgetRestoreRequestView.as_view(), name="widget-restore-request-v1"),
    path("v1/widget/restore", WidgetRestoreRedeemView.as_view(), name="widget-restore-v1"),
    # SupportHog Slack app
    re_path(r"^v1/slack/events/?$", supporthog_event_handler, name="supporthog-slack-events"),
    re_path(r"^v1/slack/authorize/?$", SupportSlackAuthorizeView.as_view(), name="supporthog-slack-authorize"),
    re_path(r"^v1/slack/callback/?$", support_slack_oauth_callback, name="supporthog-slack-callback"),
    re_path(r"^v1/slack/disconnect/?$", SupportSlackDisconnectView.as_view(), name="supporthog-slack-disconnect"),
    re_path(r"^v1/slack/channels/?$", SlackChannelsView.as_view(), name="slack-channels"),
    # Email channel
    re_path(r"^v1/email/inbound/?$", email_inbound_handler, name="email-inbound"),
    re_path(r"^v1/email/status/?$", EmailStatusView.as_view(), name="email-status"),
    re_path(r"^v1/email/connect/?$", EmailConnectView.as_view(), name="email-connect"),
    re_path(r"^v1/email/disconnect/?$", EmailDisconnectView.as_view(), name="email-disconnect"),
    path("external/ticket/<uuid:ticket_id>", ExternalTicketView.as_view(), name="external-ticket"),
]
