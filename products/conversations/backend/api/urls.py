"""URL configuration for Conversations widget and external API."""

from django.urls import path, re_path

from .email_events import email_inbound_handler
from .email_settings import (
    EmailConnectView,
    EmailDisconnectView,
    EmailSendTestView,
    EmailStatusView,
    EmailVerifyDomainView,
)
from .external import ExternalTicketView
from .github_setup import (
    GithubConnectView,
    GithubCreateIssueView,
    GithubDisconnectView,
    GithubReposView,
    GithubSelectReposView,
    GithubStatusView,
)
from .restore import WidgetRestoreRedeemView, WidgetRestoreRequestView
from .slack_channels import SlackChannelsView
from .slack_events import supporthog_event_handler
from .slack_oauth import SupportSlackAuthorizeView, SupportSlackDisconnectView, support_slack_oauth_callback
from .teams_channels import TeamsChannelsView, TeamsInstallAppView, TeamsSelectChannelView, TeamsTeamsView
from .teams_events import teams_event_handler
from .teams_oauth import TeamsAuthorizeView, TeamsDisconnectView, teams_oauth_callback
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
    # SupportHog Teams app
    re_path(r"^v1/teams/events/?$", teams_event_handler, name="supporthog-teams-events"),
    re_path(r"^v1/teams/authorize/?$", TeamsAuthorizeView.as_view(), name="supporthog-teams-authorize"),
    re_path(r"^v1/teams/callback/?$", teams_oauth_callback, name="supporthog-teams-callback"),
    re_path(r"^v1/teams/disconnect/?$", TeamsDisconnectView.as_view(), name="supporthog-teams-disconnect"),
    re_path(r"^v1/teams/teams/?$", TeamsTeamsView.as_view(), name="teams-teams"),
    re_path(r"^v1/teams/channels/?$", TeamsChannelsView.as_view(), name="teams-channels"),
    re_path(r"^v1/teams/install/?$", TeamsInstallAppView.as_view(), name="teams-install"),
    re_path(r"^v1/teams/select-channel/?$", TeamsSelectChannelView.as_view(), name="teams-select-channel"),
    # Email channel
    re_path(r"^v1/email/inbound/?$", email_inbound_handler, name="email-inbound"),
    re_path(r"^v1/email/status/?$", EmailStatusView.as_view(), name="email-status"),
    re_path(r"^v1/email/connect/?$", EmailConnectView.as_view(), name="email-connect"),
    re_path(r"^v1/email/disconnect/?$", EmailDisconnectView.as_view(), name="email-disconnect"),
    re_path(r"^v1/email/verify-domain/?$", EmailVerifyDomainView.as_view(), name="email-verify-domain"),
    re_path(r"^v1/email/send-test/?$", EmailSendTestView.as_view(), name="email-send-test"),
    # GitHub Issues channel
    re_path(r"^v1/github/status/?$", GithubStatusView.as_view(), name="github-status"),
    re_path(r"^v1/github/connect/?$", GithubConnectView.as_view(), name="github-connect"),
    re_path(r"^v1/github/disconnect/?$", GithubDisconnectView.as_view(), name="github-disconnect"),
    re_path(r"^v1/github/repos/?$", GithubReposView.as_view(), name="github-repos"),
    re_path(r"^v1/github/select-repos/?$", GithubSelectReposView.as_view(), name="github-select-repos"),
    re_path(r"^v1/github/create-issue/?$", GithubCreateIssueView.as_view(), name="github-create-issue"),
    path("external/ticket/<uuid:ticket_id>", ExternalTicketView.as_view(), name="external-ticket"),
]
