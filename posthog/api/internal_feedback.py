from django.conf import settings

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from slack_sdk.errors import SlackApiError

from posthog.auth import SessionAuthentication
from posthog.constants import POSTHOG_INTERNAL_EMAIL_SUFFIX
from posthog.egress.slack.client import SlackWebClient
from posthog.models import User
from posthog.permissions import APIScopePermission
from posthog.rate_limit import InternalFeedbackUserThrottle
from posthog.slack.formatting import escape_slack_mrkdwn

logger = structlog.get_logger(__name__)

MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024


def is_posthog_staff_email(user: User) -> bool:
    # Only a verified address proves ownership. Older accounts carry None, and an email change can set an
    # unowned address without verification when email delivery is off, so None is refused too.
    return (
        bool(user.email)
        and user.email.lower().endswith(POSTHOG_INTERNAL_EMAIL_SUFFIX)
        and user.is_email_verified is True
    )


class IsPostHogStaffEmail(BasePermission):
    message = "Internal feedback is only available to PostHog team members."

    def has_permission(self, request: Request, view: object) -> bool:
        return isinstance(request.user, User) and is_posthog_staff_email(request.user)


class InternalFeedbackRequestSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=4000, help_text="What the person wants to tell the developers.")
    page_url = serializers.URLField(max_length=2000, help_text="URL of the page the feedback is about.")
    element_identifier = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
        help_text="CSS selector of the element the person selected. Empty for feedback about the whole page.",
    )
    screenshot = serializers.ImageField(
        required=False, help_text="JPEG screenshot of the page, with the selected element outlined when there is one."
    )

    def validate_screenshot(self, value):
        if value is not None and value.size > MAX_SCREENSHOT_BYTES:
            raise serializers.ValidationError("Screenshot must be smaller than 5 MB.")
        return value


class InternalFeedbackResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(help_text="True when the feedback reached Slack.")


def build_feedback_message(user: User, page_url: str, element_identifier: str, comment: str) -> str:
    name = escape_slack_mrkdwn(user.get_full_name() or user.email)
    lines = [
        f"*New UI feedback from {name}* ({escape_slack_mrkdwn(user.email)})",
        f"*Page:* {escape_slack_mrkdwn(page_url)}",
    ]
    if element_identifier:
        # A backtick would end the inline code span early.
        identifier = escape_slack_mrkdwn(element_identifier).replace("`", "'")
        lines.append(f"*Element:* `{identifier}`")
    else:
        lines.append("*Element:* whole page")
    lines += ["", escape_slack_mrkdwn(comment)]
    return "\n".join(lines)


@extend_schema(extensions={"x-product": "platform_features"})
class InternalFeedbackViewSet(viewsets.ViewSet):
    # Session-only and INTERNAL: this is a staff tool in the web app, never an API for tokens.
    scope_object = "INTERNAL"
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, IsPostHogStaffEmail]
    throttle_classes = [InternalFeedbackUserThrottle]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        description="Send feedback about an element or page of the PostHog web app to the team's Slack channel.",
        # A raw dict, not the serializer: drf-spectacular types an ImageField as a plain string here,
        # which a generated client cannot fill with a file. Same workaround as `MediaViewSet.create`.
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "comment": {
                        "type": "string",
                        "maxLength": 4000,
                        "description": "What the person wants to tell the developers.",
                    },
                    "page_url": {
                        "type": "string",
                        "format": "uri",
                        "maxLength": 2000,
                        "description": "URL of the page the feedback is about.",
                    },
                    "element_identifier": {
                        "type": "string",
                        "maxLength": 1000,
                        "description": "CSS selector of the element the person selected. Empty for feedback about the whole page.",
                    },
                    "screenshot": {
                        "type": "string",
                        "format": "binary",
                        "description": "JPEG screenshot of the page, with the selected element outlined when there is one.",
                    },
                },
                "required": ["comment", "page_url"],
            }
        },
        responses={
            200: InternalFeedbackResponseSerializer,
            503: OpenApiResponse(description="Slack delivery is not configured or Slack refused the message."),
        },
    )
    def create(self, request: Request) -> Response:
        serializer = InternalFeedbackRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        token = settings.INTERNAL_FEEDBACK_SLACK_BOT_TOKEN
        channel = settings.INTERNAL_FEEDBACK_SLACK_CHANNEL
        if not token or not channel:
            return Response(
                {"detail": "Feedback delivery is not set up on this instance."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        user = request.user
        assert isinstance(user, User)
        message = build_feedback_message(user, data["page_url"], data["element_identifier"], data["comment"])
        client = SlackWebClient(token=token, source="internal_feedback")
        try:
            screenshot = data.get("screenshot")
            if screenshot is not None:
                client.files_upload_v2(
                    channel=channel,
                    content=screenshot.read(),
                    filename="screenshot.jpg",
                    title="Screenshot",
                    initial_comment=message,
                )
            else:
                client.chat_postMessage(channel=channel, text=message, unfurl_links=False)
        except SlackApiError as e:
            logger.exception("internal_feedback_slack_failed", error=e.response.get("error"))
            return Response(
                {"detail": "Slack did not accept the feedback. Try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(InternalFeedbackResponseSerializer({"success": True}).data)
