import json
import os
from typing import Optional
from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone
from prometheus_client import Counter
from sentry_sdk import capture_exception
import structlog

from posthog.database_healthcheck import DATABASE_FOR_FLAG_MATCHING
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.utils import UUIDModel, execute_with_timeout

from posthog.models.team import Team

CELERY_TASK_REMOTE_CONFIG_SYNC = Counter(
    "posthog_remote_config_sync",
    "Number of times the remote config sync task has been run",
    labelnames=["result"],
)

logger = structlog.get_logger(__name__)


# Load the JS content from the frontend build


_array_js_content: Optional[str] = None


def get_array_js_content():
    global _array_js_content

    if _array_js_content is None:
        with open(os.path.join(settings.BASE_DIR, "frontend/dist/array.js")) as f:
            _array_js_content = f.read()

    return _array_js_content


class RemoteConfig(UUIDModel):
    """
    RemoteConfig is a helper model. There is one per team and stores a highly cacheable JSON object
    as well as JS code for the frontend. It's main function is to react to changes that would affect it,
    update the JSON/JS configs and then sync to the optimized CDN endpoints (such as S3) as well as redis for our legacy
    /decide fallback
    """

    team = models.OneToOneField("Team", on_delete=models.CASCADE)
    config = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)
    synced_at = models.DateTimeField(null=True)

    def build_config(self):
        from posthog.models.feature_flag import FeatureFlag
        from posthog.models.team import Team
        from posthog.plugins.site import get_decide_site_apps

        # NOTE: It is important this is changed carefully. This is what the SDK will load in place of "decide" so the format
        # should be kept consistent. The JS code should be minified and the JSON should be as small as possible.
        # It is very close to the original decide payload but with fewer options as it is new and allowed us to drop some old values

        team: Team = self.team

        # NOTE: Let's try and keep this tidy! Follow the styling of the values already here...
        config = {
            "token": team.api_token,
            "supportedCompression": ["gzip", "gzip-js"],
            "hasFeatureFlags": FeatureFlag.objects.filter(team=team, active=True, deleted=False).count() > 0,
            "captureDeadClicks": bool(team.capture_dead_clicks),
            "capturePerformance": (
                {
                    "network_timing": bool(team.capture_performance_opt_in),
                    "web_vitals": bool(team.autocapture_web_vitals_opt_in),
                    "web_vitals_allowed_metrics": team.autocapture_web_vitals_allowed_metrics,
                }
                if team.capture_performance_opt_in or team.autocapture_web_vitals_opt_in
                else False
            ),
            "autocapture_opt_out": bool(team.autocapture_opt_out),
            "autocaptureExceptions": (
                {
                    "endpoint": "/e/",
                }
                if team.autocapture_exceptions_opt_in
                else False
            ),
            "analytics": {"endpoint": settings.NEW_ANALYTICS_CAPTURE_ENDPOINT},
        }

        if str(team.id) not in (settings.ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS or []):
            config["elementsChainAsString"] = True

        # MARK: Session Recording
        session_recording_config_response: bool | dict = False

        # TODO: Support the domain based check for recordings (maybe do it client side)?
        if team.session_recording_opt_in:
            sample_rate = team.session_recording_sample_rate or None
            if sample_rate == "1.00":
                sample_rate = None

            linked_flag = None
            linked_flag_config = team.session_recording_linked_flag or None
            if isinstance(linked_flag_config, dict):
                linked_flag_key = linked_flag_config.get("key", None)
                linked_flag_variant = linked_flag_config.get("variant", None)
                if linked_flag_variant is not None:
                    linked_flag = {"flag": linked_flag_key, "variant": linked_flag_variant}
                else:
                    linked_flag = linked_flag_key

            session_recording_config_response = {
                "endpoint": "/s/",
                "consoleLogRecordingEnabled": True if team.capture_console_log_opt_in else False,
                "recorderVersion": "v2",
                "sampleRate": str(sample_rate) if sample_rate else None,
                "minimumDurationMilliseconds": team.session_recording_minimum_duration_milliseconds or None,
                "linkedFlag": linked_flag,
                "networkPayloadCapture": team.session_recording_network_payload_capture_config or None,
                "urlTriggers": team.session_recording_url_trigger_config,
                "urlBlocklist": team.session_recording_url_blocklist_config,
                "eventTriggers": team.session_recording_event_trigger_config,
            }

            if isinstance(team.session_replay_config, dict):
                record_canvas = team.session_replay_config.get("record_canvas", False)
                session_recording_config_response.update(
                    {
                        "recordCanvas": record_canvas,
                        # hard coded during beta while we decide on sensible values
                        "canvasFps": 3 if record_canvas else None,
                        "canvasQuality": "0.4" if record_canvas else None,
                    }
                )
        config["sessionRecording"] = session_recording_config_response

        # MARK: Quota limiting
        if settings.EE_AVAILABLE:
            from ee.billing.quota_limiting import (
                QuotaLimitingCaches,
                QuotaResource,
                list_limited_team_attributes,
            )

            limited_tokens_recordings = list_limited_team_attributes(
                QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )

            if team.api_token in limited_tokens_recordings:
                config["quotaLimited"] = ["recordings"]
                config["sessionRecording"] = False

        config["surveys"] = True if team.surveys_opt_in else False
        config["heatmaps"] = True if team.heatmaps_opt_in else False
        try:
            default_identified_only = team.pk >= int(settings.DEFAULT_IDENTIFIED_ONLY_TEAM_ID_MIN)
        except Exception:
            default_identified_only = False
        config["defaultIdentifiedOnly"] = bool(default_identified_only)

        # MARK: Site apps - we want to eventually inline the JS but that will come later
        site_apps = []
        if team.inject_web_apps:
            try:
                with execute_with_timeout(200, DATABASE_FOR_FLAG_MATCHING):
                    site_apps = get_decide_site_apps(team, using_database=DATABASE_FOR_FLAG_MATCHING)
            except Exception:
                pass

        config["siteApps"] = site_apps

        return config

    def build_js_config(self):
        # NOTE: This is the web focused config for the frontend that includes site apps

        from posthog.plugins.site import get_site_apps_for_team, get_site_config_from_schema

        # Add in the site apps as an array of objects
        site_apps = []
        for site_app in get_site_apps_for_team(self.team.id):
            config = get_site_config_from_schema(site_app.config_schema, site_app.config)
            # NOTE: It is an object as we can later add other properties such as a consent ID
            site_apps.append(
                f"{{ token: '{site_app.token}', load: function(posthog) {{ {site_app.source}().inject({{ config:{json.dumps(config)}, posthog:posthog }}) }} }}"
            )

        js_content = f"""
        (function() {{
            window._POSTHOG_CONFIG = {json.dumps(self.config)};
            window._POSTHOG_SITE_APPS = [{','.join(site_apps)}];
        }})();
        """.strip()

        return js_content

    def build_array_js_config(self):
        # NOTE: This is the JS that will be loaded by the SDK.
        # It includes the dist JS for the frontend and the JSON config

        js_content = self.build_js_config()

        js_content = f"""
        {get_array_js_content()}

        {js_content}
        """

        return js_content

    def sync(self, force=False):
        """
        When called we sync to any configured CDNs as well as redis for the /decide endpoint
        """

        logger.info(f"Syncing RemoteConfig for team {self.team_id}")

        try:
            config = self.build_config()
            # Compare the config to the current one and only update if it has changed
            if config == self.config and not force:
                logger.info(f"RemoteConfig for team {self.team_id} has not changed. Skipping sync.")
                return

            self.config = config
            # TODO: Invalidate caches - in particular this will be the Cloudflare CDN cache
            self.synced_at = timezone.now()
            self.save()

            CELERY_TASK_REMOTE_CONFIG_SYNC.labels(result="success").inc()
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to sync RemoteConfig for team {self.team_id}", exception=str(e))
            CELERY_TASK_REMOTE_CONFIG_SYNC.labels(result="failure").inc()
            raise

    def __str__(self):
        return f"RemoteConfig {self.team_id}"


def rebuild_remote_config(team: "Team"):
    from posthog.tasks.remote_config import update_team_remote_config

    update_team_remote_config.delay(team.id)


@receiver(post_save, sender=Team)
def team_saved(sender, instance: "Team", created, **kwargs):
    rebuild_remote_config(instance)


@receiver(post_save, sender=FeatureFlag)
def feature_flag_saved(sender, instance: "FeatureFlag", created, **kwargs):
    rebuild_remote_config(instance.team)
