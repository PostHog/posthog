import re
from typing import Any
from urllib.parse import urlparse

import structlog

from posthog.integrations import IntegrationManager
from posthog.models.integration import SlackIntegration
from posthog.models.sharing_configuration import SharingConfiguration

from products.subscriptions.backend.facade.api import render_shared_insight_image

logger = structlog.get_logger(__name__)


SHARED_LINK_REGEX = r"\/(?:shared_dashboard|shared|embedded)\/(.+)"


def _handle_slack_event(event_payload: Any) -> None:
    slack_team_id = event_payload.get("team_id")
    channel = event_payload.get("event").get("channel")
    message_ts = event_payload.get("event").get("message_ts")
    unfurl_id = event_payload.get("event").get("unfurl_id")
    source = event_payload.get("event").get("source")
    links_to_unfurl = event_payload.get("event").get("links")

    unfurls = {}

    for link_obj in links_to_unfurl:
        link = link_obj.get("url")
        parsed = urlparse(link)
        matches = re.search(SHARED_LINK_REGEX, parsed.path)

        if matches:
            share_token = matches[1]

            # First we try and get the sharingconfig for the given link
            try:
                sharing_config: SharingConfiguration = SharingConfiguration.objects.filter(
                    SharingConfiguration.without_retired_resources_q()
                ).get(access_token=share_token, enabled=True)
            except SharingConfiguration.DoesNotExist:
                logger.info("No SharingConfiguration found")
                continue

            team_id = sharing_config.team_id

            # Now we try and get the SlackIntegration for the specificed PostHog team and Slack Team
            # `where` compares top-level config keys only, so match the nested Slack team id here.
            integration = next(
                (
                    row
                    for row in IntegrationManager.slack.oauth.list(team_id)
                    if ((row.config or {}).get("team") or {}).get("id") == slack_team_id
                ),
                None,
            )
            if integration is None:
                logger.info("No SlackIntegration found for this team")
                continue
            slack_integration = SlackIntegration(integration)

            # With both the integration and the resource we are good to go!!

            # Usage breadcrumb: this legacy Celery-backed image unfurl is believed superseded by the
            # metadata-only products/slack_app unfurl. It renders a PNG via the EXPORTS Celery queue,
            # which has no in-container Chromium (removed) and no BROWSERLESS_CDP_URL — so a real hit
            # here both proves the path is live AND would fail to render. Logged at warning so it's
            # impossible to miss while we decide whether to keep/retire it.
            logger.warning(
                "slack_legacy_image_unfurl.invoked",
                team_id=team_id,
                sharing_configuration_id=sharing_config.id,
            )

            image = render_shared_insight_image(sharing_config)

            if image:
                unfurls[link] = {
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": image.title,
                            },
                            "accessory": {"type": "image", "image_url": image.image_url, "alt_text": image.alt_text},
                        }
                    ]
                }

    if unfurls:
        try:
            slack_integration.client.chat_unfurl(unfurls=unfurls, unfurl_id=unfurl_id, source=source, channel="", ts="")
        except Exception:
            # NOTE: This is temporary as a test to understand if the channel and ts are actually required as the docs are not clear
            slack_integration.client.chat_unfurl(
                unfurls=unfurls,
                unfurl_id=unfurl_id,
                source=source,
                channel=channel,
                ts=message_ts,
            )
            raise


def handle_slack_event(payload: Any) -> None:
    return _handle_slack_event(payload)
