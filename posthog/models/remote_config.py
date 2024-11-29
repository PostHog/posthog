import json
import os
from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone
import structlog

from posthog.database_healthcheck import DATABASE_FOR_FLAG_MATCHING
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.utils import UUIDModel, execute_with_timeout

from posthog.models.team import Team

logger = structlog.get_logger(__name__)


# TODO list
# - Add a listener for when a site app is created/updated/deleted
# - Add tests to ensure that decide uses this config perfectly
# - Add JS loader that includes only config and other assets (site apps)
# - Add JS loader including posthog-js
# - Some way of detecting change to array.js and triggering a refresh job of all configs

# Load the JS content from the frontend buil
ARRAY_JS_CONTENT_FILE = os.path.join(settings.BASE_DIR, "frontend/dist/array.js")
ARRAY_JS_CONTENT = open(ARRAY_JS_CONTENT_FILE).read()


class RemoteConfig(UUIDModel):
    """
    RemoteConfig is a helper model. There is one per team and stores a highly cacheable JSON object
    as well as JS code for the frontend. It's main function is to react to changes that would affect it,
    update the JSON/JS configs and then sync to the optimized CDN endpoints (such as S3) as well as redis for our legacy
    /decide fallback
    """

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    config = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)
    synced_at = models.DateTimeField(null=True)

    @property
    def sync_pending(self):
        return self.updated_at > self.synced_at if self.synced_at else True

    def build_config(self):
        from posthog.models.feature_flag import FeatureFlag
        from posthog.models.team import Team
        from posthog.plugins.site import get_decide_site_apps

        # NOTE: It is important this is changed carefully. This is what the SDK will load in place of "decide" so the format
        # should be kept consistent. The JS code should be minified and the JSON should be as small as possible.
        # It is very close to the original decide payload but with fewer options as it is new and allowed us to drop some old values

        team: Team = self.team

        # TODO: Add the token to the config so that it is verifiable as a standalone file
        # NOTE: Let's try and keep this tidy! Follow the styling of the values already here...
        config = {
            "supported_compression": ["gzip", "gzip-js"],
            "has_feature_flags": FeatureFlag.objects.filter(team=team, active=True, deleted=False).count() > 0,
            "capture_dead_clicks": bool(team.capture_dead_clicks),
            "capture_performance": (
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
            # TODO: IDeally get rid of this as it seems very old and redundant
            "elements_chain_as_string": True,
        }

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
                "sampleRate": sample_rate,
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
        config["session_recording"] = session_recording_config_response

        # MARK: Quota limiting
        if settings.EE_AVAILABLE:
            # NOTE: Add listener for quota limits changing
            from ee.billing.quota_limiting import (
                QuotaLimitingCaches,
                QuotaResource,
                list_limited_team_attributes,
            )

            limited_tokens_recordings = list_limited_team_attributes(
                QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )

            if team.api_token in limited_tokens_recordings:
                config["quota_limited"] = ["recordings"]
                config["sessionRecording"] = False

        config["surveys"] = True if team.surveys_opt_in else False
        config["heatmaps"] = True if team.heatmaps_opt_in else False
        try:
            default_identified_only = team.pk >= int(settings.DEFAULT_IDENTIFIED_ONLY_TEAM_ID_MIN)
        except Exception:
            default_identified_only = False
        config["default_identified_only"] = bool(default_identified_only)

        # MARK: Site apps - we want to eventually inline the JS but that will come later
        site_apps = []
        if team.inject_web_apps:
            try:
                with execute_with_timeout(200, DATABASE_FOR_FLAG_MATCHING):
                    site_apps = get_decide_site_apps(team, using_database=DATABASE_FOR_FLAG_MATCHING)
            except Exception:
                pass

        config["site_apps"] = site_apps

        return config

    def build_js_config(self):
        # NOTE: This is the web focused config for the frontend that includes site apps

        from posthog.plugins.site import get_site_apps_for_team, get_site_config_from_schema

        # Add in the site apps as an array of objects
        # TODO: Should this be an array??
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
        {js_content}
        {ARRAY_JS_CONTENT}
        """

        return js_content

    def sync(self):
        """
        When called we sync to any configured CDNs as well as redis for the /decide endpoint
        """

        self.config = self.build_config()
        self.synced_at = timezone.now()
        self.save()

    def __str__(self):
        return f"RemoteConfig {self.team_id}"


def rebuild_remote_config(team: "Team"):
    # TODO: Add metrics so that we can graph and alert on this. Capture exceptions for errors as these will be critical
    logger.info("RemoteConfig rebuild triggered", team_id=team.id)
    try:
        remote_config = RemoteConfig.objects.get(team=team)
    except RemoteConfig.DoesNotExist:
        remote_config = RemoteConfig(team=team)

    remote_config.sync()


@receiver(post_save, sender=Team)
def team_saved(sender, instance: "Team", created, **kwargs):
    rebuild_remote_config(instance)


@receiver(post_save, sender=FeatureFlag)
def feature_flag_saved(sender, instance: "FeatureFlag", created, **kwargs):
    rebuild_remote_config(instance.team)
