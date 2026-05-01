import json
from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone

import requests
import structlog
from opentelemetry import trace
from prometheus_client import Counter

from posthog.database_healthcheck import DATABASE_FOR_FLAG_MATCHING
from posthog.exceptions_capture import capture_exception
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.js_snippet_versioning import DEFAULT_SNIPPET_VERSION
from posthog.models.plugin import PluginConfig
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.js_snippet_config import TeamJsSnippetConfig
from posthog.models.team.team import Team
from posthog.models.utils import UUIDTModel, execute_with_timeout
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing

from products.error_tracking.backend.models import ErrorTrackingSuppressionRule
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

tracer = trace.get_tracer(__name__)

CELERY_TASK_REMOTE_CONFIG_SYNC = Counter(
    "posthog_remote_config_sync",
    "Number of times the remote config sync task has been run",
    labelnames=["result"],
)

REMOTE_CONFIG_CDN_PURGE_COUNTER = Counter(
    "posthog_remote_config_cdn_purge",
    "Number of times the remote config CDN purge task has been run",
    labelnames=["result"],
)


logger = structlog.get_logger(__name__)


@tracer.start_as_current_span("RemoteConfig.indent_js")
def indent_js(js_content: str, indent: int = 4) -> str:
    joined = "\n".join([f"{' ' * indent}{line}" for line in js_content.split("\n")])

    return joined


class RemoteConfig(UUIDTModel):
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

    @classmethod
    def get_hypercache(cls):
        def load_config(token):
            try:
                return RemoteConfig.objects.select_related("team").get(team__api_token=token).build_config()
            except RemoteConfig.DoesNotExist:
                return HyperCacheStoreMissing()

        return HyperCache(
            namespace="array",
            value="config.json",
            token_based=True,  # We store and load via the team token
            load_fn=load_config,
        )

    def _build_session_recording_config(self, team: Team) -> dict:
        """
        Build session recording configuration with V1/V2 support.

        V2: If team.session_recording_trigger_groups is set, use new trigger groups format
        V1: Otherwise, use legacy trigger fields for backward compatibility
        """
        # Build base config (common to both V1 and V2)
        capture_console_logs = True if team.capture_console_log_opt_in else False
        minimum_duration = team.session_recording_minimum_duration_milliseconds or None

        rrweb_script_config = None
        recorder_script = team.extra_settings.get("recorder_script") if team.extra_settings else None
        if not recorder_script and settings.DEBUG:
            recorder_script = "posthog-recorder"
        if recorder_script:
            rrweb_script_config = {"script": recorder_script}

        record_canvas = False
        canvas_fps = None
        canvas_quality = None
        if isinstance(team.session_replay_config, dict):
            record_canvas = team.session_replay_config.get("record_canvas", False)
            if record_canvas:
                canvas_fps = 3
                canvas_quality = "0.4"

        base_config = {
            "endpoint": "/s/",
            "consoleLogRecordingEnabled": capture_console_logs,
            "recorderVersion": "v2",
            "minimumDurationMilliseconds": minimum_duration,
            "networkPayloadCapture": team.session_recording_network_payload_capture_config or None,
            "masking": team.session_recording_masking_config or None,
            "urlBlocklist": team.session_recording_url_blocklist_config,
            "scriptConfig": rrweb_script_config,
            "domains": team.recording_domains or [],
            "recordCanvas": record_canvas,
            "canvasFps": canvas_fps,
            "canvasQuality": canvas_quality,
        }

        # Build V1 fields (for backward compatibility with old SDKs)
        sample_rate = (
            str(team.session_recording_sample_rate.normalize())
            if team.session_recording_sample_rate is not None
            else None
        )
        if sample_rate == "1":
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

        v1_fields = {
            "sampleRate": sample_rate,
            "linkedFlag": linked_flag,
            "urlTriggers": team.session_recording_url_trigger_config,
            "eventTriggers": team.session_recording_event_trigger_config,
            "triggerMatchType": team.session_recording_trigger_match_type_config,
        }

        # V2: If trigger groups configured, send V2 + V1 fallback fields
        if team.session_recording_trigger_groups:
            trigger_groups_config = team.session_recording_trigger_groups
            groups = trigger_groups_config.get("groups", [])

            # Normalize events to objects for SDK: ["purchase"] -> [{"name": "purchase"}]
            # This future-proofs the contract so WHERE clauses (property filters on events)
            # can be added later without a breaking SDK change.
            # Build normalized copies to avoid mutating the team's stored data.
            normalized_groups = []
            for group in groups:
                conditions = group.get("conditions", {})
                if "events" in conditions:
                    group = {
                        **group,
                        "conditions": {
                            **conditions,
                            "events": [{"name": e} if isinstance(e, str) else e for e in conditions["events"]],
                        },
                    }
                normalized_groups.append(group)

            return {
                **base_config,
                "version": 2,
                "triggerGroups": normalized_groups,
                # Include V1 fields for backward compatibility with old SDKs
                **v1_fields,
            }

        # V1 only: Use legacy trigger fields
        return {
            **base_config,
            "version": 1,
            **v1_fields,
        }

    @tracer.start_as_current_span("RemoteConfig.build_config")
    def build_config(self):
        from posthog.models.feature_flag import FeatureFlag
        from posthog.models.team import Team
        from posthog.plugins.site import get_decide_site_apps

        from products.error_tracking.backend.remote_config import build_error_tracking_config
        from products.surveys.backend.api.survey import get_surveys_opt_in, get_surveys_response

        # NOTE: It is important this is changed carefully. This is what the SDK will load in place of "decide" so the format
        # should be kept consistent. The JS code should be minified and the JSON should be as small as possible.
        # It is very close to the original decide payload but with fewer options as it is new and allowed us to drop some old values

        team: Team = self.team

        # NOTE: Let's try and keep this tidy! Follow the styling of the values already here...
        config = {
            "token": team.api_token,
            "supportedCompression": ["gzip", "gzip-js"],
            "hasFeatureFlags": FeatureFlag.objects.filter(team=team, active=True).count() > 0,
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
            "autocaptureExceptions": bool(team.autocapture_exceptions_opt_in),
        }

        if str(team.id) not in (settings.NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS or []):
            config["analytics"] = {"endpoint": settings.NEW_ANALYTICS_CAPTURE_ENDPOINT}

        if str(team.id) not in (settings.ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS or []):
            config["elementsChainAsString"] = True

        # MARK: Error tracking
        config["errorTracking"] = build_error_tracking_config(team)

        # MARK: Logs
        logs_settings = team.logs_settings or {}
        config["logs"] = {
            "captureConsoleLogs": logs_settings.get("capture_console_logs", False),
        }

        # MARK: Session recording
        session_recording_config_response: bool | dict = False

        # TODO: Support the domain based check for recordings (maybe do it client side)?
        if team.session_recording_opt_in:
            session_recording_config_response = self._build_session_recording_config(team)

        config["sessionRecording"] = session_recording_config_response

        # MARK: Quota limiting
        if settings.EE_AVAILABLE:
            from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes

            limited_tokens_recordings = list_limited_team_attributes(
                QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )

            if team.api_token in limited_tokens_recordings:
                config["quotaLimited"] = ["recordings"]
                config["sessionRecording"] = False

        config["heatmaps"] = True if team.heatmaps_opt_in else False

        # MARK: Conversations
        if team.conversations_enabled:
            conv_settings = team.conversations_settings or {}
            config["conversations"] = {
                "enabled": True,
                "widgetEnabled": conv_settings.get("widget_enabled", False),
                "greetingText": conv_settings.get("widget_greeting_text") or "Hey, how can I help you today?",
                "color": conv_settings.get("widget_color") or "#1d4aff",
                "token": conv_settings.get("widget_public_token"),
                # NOTE: domains is cached but stripped out at the api level depending on the caller
                "domains": conv_settings.get("widget_domains") or [],
                "requireEmail": conv_settings.get("widget_require_email", False),
                "collectName": conv_settings.get("widget_collect_name", False),
                "identificationFormTitle": conv_settings.get("widget_identification_form_title")
                or "Before we start...",
                "identificationFormDescription": conv_settings.get("widget_identification_form_description")
                or "Please provide your details so we can help you better.",
                "placeholderText": conv_settings.get("widget_placeholder_text") or "Type your message...",
                "widgetPosition": conv_settings.get("widget_position") or "bottom_right",
            }
        else:
            config["conversations"] = False

        surveys_opt_in = get_surveys_opt_in(team)

        if surveys_opt_in:
            surveys_response = get_surveys_response(team)
            surveys = surveys_response["surveys"]
            if len(surveys) > 0:
                config["surveys"] = surveys_response["surveys"]

                if surveys_response["survey_config"]:
                    config["survey_config"] = surveys_response["survey_config"]
            else:
                config["surveys"] = False
        else:
            config["surveys"] = False

        # MARK: Product tours
        # Only query if the team has opted in (auto-set when a tour is created)
        if team.product_tours_opt_in:
            has_active_tours = ProductTour.objects.filter(
                team=team,
                archived=False,
                start_date__isnull=False,
            ).exists()
            config["productTours"] = has_active_tours
        else:
            config["productTours"] = False

        config["defaultIdentifiedOnly"] = True  # Support old SDK versions with setting that is now the default

        # MARK: Site apps - we want to eventually inline the JS but that will come later
        site_apps = []
        if team.inject_web_apps:
            try:
                with execute_with_timeout(200, DATABASE_FOR_FLAG_MATCHING):
                    site_apps = get_decide_site_apps(team, using_database=DATABASE_FOR_FLAG_MATCHING)
            except Exception:
                pass

        config["siteApps"] = site_apps
        # Array of JS objects to be included when building the final JS
        config["siteAppsJS"] = self._build_site_apps_js()

        # MARK: Snippet versioning — store requested version, resolved at request time
        if settings.POSTHOG_JS_S3_BUCKET:
            snippet_config = get_or_create_team_extension(team, TeamJsSnippetConfig)
            config["sdkVersion"] = {"requested": snippet_config.js_snippet_version or DEFAULT_SNIPPET_VERSION}

        return config

    @tracer.start_as_current_span("RemoteConfig._build_site_apps_js")
    def _build_site_apps_js(self):
        # NOTE: This is the web focused config for the frontend that includes site apps

        from posthog.cdp.site_functions import get_transpiled_function
        from posthog.models import HogFunction
        from posthog.plugins.site import get_site_apps_for_team, get_site_config_from_schema

        # Add in the site apps as an array of objects
        site_apps_js = []
        for site_app in get_site_apps_for_team(self.team.id):
            config = get_site_config_from_schema(site_app.config_schema, site_app.config)
            site_apps_js.append(
                indent_js(
                    f"\n{{\n  id: '{site_app.token}',\n  init: function(config) {{\n    {indent_js(site_app.source, indent=4)}().inject({{ config:{json.dumps(config)}, posthog:config.posthog }});\n    config.callback(); return {{}}  }}\n}}"
                )
            )
        site_functions = (
            HogFunction.objects.select_related("team")
            .filter(
                team=self.team,
                enabled=True,
                deleted=False,
                type__in=("site_destination", "site_app"),
            )
            .all()
        )

        site_functions_js = []

        for site_function in site_functions:
            try:
                source = get_transpiled_function(site_function)
                # NOTE: It is an object as we can later add other properties such as a consent ID
                # Indentation to make it more readable (and therefore debuggable)
                site_functions_js.append(
                    indent_js(
                        f"\n{{\n  id: '{site_function.id}',\n  init: function(config) {{ return {indent_js(source, indent=4)}().init(config) }} \n}}"
                    )
                )
            except Exception:
                # TODO: Should we track this to somewhere?
                logger.exception(f"Failed to build JS for site function {site_function.id}")
                pass

        return site_apps_js + site_functions_js

    def sync(self, force: bool = False):
        """
        When called we sync to any configured CDNs as well as redis for the /decide endpoint
        """

        logger.info(f"Syncing RemoteConfig for team {self.team_id}")

        try:
            config = self.build_config()

            if not force and config == self.config:
                CELERY_TASK_REMOTE_CONFIG_SYNC.labels(result="no_changes").inc()
                logger.info(f"RemoteConfig for team {self.team_id} is unchanged")
                return

            self.config = config
            self.synced_at = timezone.now()
            self.save()

            try:
                RemoteConfig.get_hypercache().update_cache(self.team.api_token)
            except Exception as e:
                logger.exception(f"Failed to update hypercache for team {self.team_id}")
                capture_exception(e)

            # Invalidate Cloudflare CDN cache
            self._purge_cdn()

            CELERY_TASK_REMOTE_CONFIG_SYNC.labels(result="success").inc()
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to sync RemoteConfig for team {self.team_id}", exception=str(e))
            CELERY_TASK_REMOTE_CONFIG_SYNC.labels(result="failure").inc()
            raise

    def _purge_cdn(self):
        if (
            not settings.REMOTE_CONFIG_CDN_PURGE_ENDPOINT
            or not settings.REMOTE_CONFIG_CDN_PURGE_TOKEN
            or not settings.REMOTE_CONFIG_CDN_PURGE_DOMAINS
        ):
            return

        data: dict[str, Any] = {"files": []}

        for domain in settings.REMOTE_CONFIG_CDN_PURGE_DOMAINS:
            # Check if the domain starts with https:// and if not add it
            full_domain = domain if domain.startswith("https://") else f"https://{domain}"
            data["files"].append({"url": f"{full_domain}/array/{self.team.api_token}/config"})
            data["files"].append({"url": f"{full_domain}/array/{self.team.api_token}/config.js"})

        logger.info(f"Purging CDN for team {self.team_id}", {"data": data})

        try:
            res = requests.post(
                settings.REMOTE_CONFIG_CDN_PURGE_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.REMOTE_CONFIG_CDN_PURGE_TOKEN}"},
                json=data,
            )

            if res.status_code != 200:
                raise Exception(f"Failed to purge CDN for team {self.team_id}: {res.status_code} {res.text}")

        except Exception:
            logger.exception(f"Failed to purge CDN for team {self.team_id}")
            REMOTE_CONFIG_CDN_PURGE_COUNTER.labels(result="failure").inc()
        else:
            REMOTE_CONFIG_CDN_PURGE_COUNTER.labels(result="success").inc()

    @staticmethod
    def purge_cdn_by_tag(tag: str):
        """Purge all CDN entries matching a Cache-Tag."""
        if not settings.REMOTE_CONFIG_CDN_PURGE_ENDPOINT or not settings.REMOTE_CONFIG_CDN_PURGE_TOKEN:
            return

        data = {"tags": [tag]}

        try:
            res = requests.post(
                settings.REMOTE_CONFIG_CDN_PURGE_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.REMOTE_CONFIG_CDN_PURGE_TOKEN}"},
                json=data,
            )
            if res.status_code != 200:
                raise Exception(f"Failed to purge CDN by tag {tag}: {res.status_code} {res.text}")
        except Exception:
            logger.exception(f"Failed to purge CDN by tag {tag}")
            REMOTE_CONFIG_CDN_PURGE_COUNTER.labels(result="failure").inc()
        else:
            REMOTE_CONFIG_CDN_PURGE_COUNTER.labels(result="success").inc()

    def __str__(self):
        return f"RemoteConfig {self.team_id}"


def _update_team_remote_config(team_id: int):
    from posthog.tasks.remote_config import update_team_remote_config

    update_team_remote_config.delay(team_id)


@receiver(post_save, sender=Team)
def team_saved(sender, instance: "Team", created, **kwargs):
    transaction.on_commit(lambda: _update_team_remote_config(instance.id))


@receiver(post_save, sender=FeatureFlag)
def feature_flag_saved(sender, instance: "FeatureFlag", created, **kwargs):
    transaction.on_commit(lambda: _update_team_remote_config(instance.team_id))


@receiver(post_save, sender=PluginConfig)
def site_app_saved(sender, instance: "PluginConfig", created, **kwargs):
    # PluginConfig allows null for team, hence this check.
    # Use intermediate variable so it's properly captured by the lambda.
    instance_team_id = instance.team_id
    if instance_team_id is not None:
        transaction.on_commit(lambda: _update_team_remote_config(instance_team_id))


@receiver(post_save, sender=HogFunction)
@receiver(post_delete, sender=HogFunction)
def site_function_changed(sender, instance: "HogFunction", **kwargs):
    if instance.type in ("site_destination", "site_app"):
        transaction.on_commit(lambda: _update_team_remote_config(instance.team_id))


@receiver(post_save, sender=Survey)
def survey_saved(sender, instance: "Survey", created, **kwargs):
    transaction.on_commit(lambda: _update_team_remote_config(instance.team_id))


def sync_team_product_tours_opt_in(team: Team) -> None:
    """Sync the product_tours_opt_in flag based on whether the team has any active tours."""
    has_active_tours = ProductTour.objects.filter(
        team=team,
        archived=False,
        start_date__isnull=False,
    ).exists()
    if has_active_tours != team.product_tours_opt_in:
        team.product_tours_opt_in = has_active_tours
        team.save(update_fields=["product_tours_opt_in"])


@receiver(post_save, sender="product_tours.ProductTour")
def product_tour_saved(sender, instance, created, **kwargs):
    def _on_commit():
        try:
            team = Team.objects.get(id=instance.team_id)
            sync_team_product_tours_opt_in(team)
        except Team.DoesNotExist:
            pass
        _update_team_remote_config(instance.team_id)

    transaction.on_commit(_on_commit)


@receiver(post_delete, sender="product_tours.ProductTour")
def product_tour_deleted(sender, instance, **kwargs):
    def _on_commit():
        try:
            team = Team.objects.get(id=instance.team_id)
            sync_team_product_tours_opt_in(team)
        except Team.DoesNotExist:
            pass
        _update_team_remote_config(instance.team_id)

    transaction.on_commit(_on_commit)


@receiver(post_save, sender=ErrorTrackingSuppressionRule)
def error_tracking_suppression_rule_saved(sender, instance: "ErrorTrackingSuppressionRule", created, **kwargs):
    transaction.on_commit(lambda: _update_team_remote_config(instance.team_id))


@receiver(post_save, sender="posthog.TeamJsSnippetConfig")
def js_snippet_config_saved(sender, instance, created, **kwargs):
    transaction.on_commit(lambda: _update_team_remote_config(instance.team_id))
