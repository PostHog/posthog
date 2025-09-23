import os
import json
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch.dispatcher import receiver
from django.http import HttpRequest
from django.utils import timezone

import requests
import structlog
from prometheus_client import Counter

from posthog.database_healthcheck import DATABASE_FOR_FLAG_MATCHING
from posthog.exceptions_capture import capture_exception
from posthog.models.error_tracking.error_tracking import ErrorTrackingSuppressionRule
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.plugin import PluginConfig
from posthog.models.surveys.survey import Survey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDTModel, execute_with_timeout
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing

CACHE_TIMEOUT = 60 * 60 * 24  # 1 day - it will be invalidated by the daily sync


CELERY_TASK_REMOTE_CONFIG_SYNC = Counter(
    "posthog_remote_config_sync",
    "Number of times the remote config sync task has been run",
    labelnames=["result"],
)

REMOTE_CONFIG_CACHE_COUNTER = Counter(
    "posthog_remote_config_via_cache",
    "Metric tracking whether a remote config was fetched from cache or not",
    labelnames=["result"],
)

REMOTE_CONFIG_CDN_PURGE_COUNTER = Counter(
    "posthog_remote_config_cdn_purge",
    "Number of times the remote config CDN purge task has been run",
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


def indent_js(js_content: str, indent: int = 4) -> str:
    joined = "\n".join([f"{' ' * indent}{line}" for line in js_content.split("\n")])

    return joined


def cache_key_for_team_token(team_token: str) -> str:
    return f"remote_config/{team_token}/config"


def sanitize_config_for_public_cdn(config: dict, request: Optional[HttpRequest] = None) -> dict:
    from posthog.api.utils import on_permitted_recording_domain

    # Remove domains from session recording
    if config.get("sessionRecording"):
        if "domains" in config["sessionRecording"]:
            domains = config["sessionRecording"].pop("domains")

            # Empty list of domains means always permitted
            if request and domains:
                if not on_permitted_recording_domain(domains, request=request):
                    config["sessionRecording"] = False

    # Remove site apps JS
    config.pop("siteAppsJS", None)
    return config


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

    def build_config(self):
        from posthog.api.error_tracking import get_suppression_rules
        from posthog.api.survey import get_surveys_opt_in, get_surveys_response
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
            "autocaptureExceptions": bool(team.autocapture_exceptions_opt_in),
        }

        if str(team.id) not in (settings.NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS or []):
            config["analytics"] = {"endpoint": settings.NEW_ANALYTICS_CAPTURE_ENDPOINT}

        if str(team.id) not in (settings.ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS or []):
            config["elementsChainAsString"] = True

        # MARK: Error tracking
        config["errorTracking"] = {
            "autocaptureExceptions": bool(team.autocapture_exceptions_opt_in),
            "suppressionRules": get_suppression_rules(team) if team.autocapture_exceptions_opt_in else [],
        }

        # MARK: Session recording
        session_recording_config_response: bool | dict = False

        # TODO: Support the domain based check for recordings (maybe do it client side)?
        if team.session_recording_opt_in:
            capture_console_logs = True if team.capture_console_log_opt_in else False
            sample_rate = (
                str(team.session_recording_sample_rate) if team.session_recording_sample_rate is not None else None
            )

            if sample_rate == "1.00":
                sample_rate = None

            minimum_duration = team.session_recording_minimum_duration_milliseconds or None

            linked_flag = None
            linked_flag_config = team.session_recording_linked_flag or None
            if isinstance(linked_flag_config, dict):
                linked_flag_key = linked_flag_config.get("key", None)
                linked_flag_variant = linked_flag_config.get("variant", None)
                if linked_flag_variant is not None:
                    linked_flag = {"flag": linked_flag_key, "variant": linked_flag_variant}
                else:
                    linked_flag = linked_flag_key

            rrweb_script_config = None

            if (settings.SESSION_REPLAY_RRWEB_SCRIPT is not None) and (
                "*" in settings.SESSION_REPLAY_RRWEB_SCRIPT_ALLOWED_TEAMS
                or str(team.id) in settings.SESSION_REPLAY_RRWEB_SCRIPT_ALLOWED_TEAMS
            ):
                rrweb_script_config = {
                    "script": settings.SESSION_REPLAY_RRWEB_SCRIPT,
                }

            session_recording_config_response = {
                "endpoint": "/s/",
                "consoleLogRecordingEnabled": capture_console_logs,
                "recorderVersion": "v2",
                "sampleRate": sample_rate,
                "minimumDurationMilliseconds": minimum_duration,
                "linkedFlag": linked_flag,
                "networkPayloadCapture": team.session_recording_network_payload_capture_config or None,
                "masking": team.session_recording_masking_config or None,
                "urlTriggers": team.session_recording_url_trigger_config,
                "urlBlocklist": team.session_recording_url_blocklist_config,
                "eventTriggers": team.session_recording_event_trigger_config,
                "triggerMatchType": team.session_recording_trigger_match_type_config,
                "scriptConfig": rrweb_script_config,
                # NOTE: This is cached but stripped out at the api level depending on the caller
                "domains": team.recording_domains or [],
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
            from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes

            limited_tokens_recordings = list_limited_team_attributes(
                QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )

            if team.api_token in limited_tokens_recordings:
                config["quotaLimited"] = ["recordings"]
                config["sessionRecording"] = False

        config["heatmaps"] = True if team.heatmaps_opt_in else False

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

        return config

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
            .filter(team=self.team, enabled=True, deleted=False, type__in=("site_destination", "site_app"))
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

    @classmethod
    def _get_config_via_cache(cls, token: str) -> dict:
        key = cache_key_for_team_token(token)

        data = cache.get(key)
        if data == "404":
            REMOTE_CONFIG_CACHE_COUNTER.labels(result="hit_but_missing").inc()
            raise cls.DoesNotExist()

        if data:
            REMOTE_CONFIG_CACHE_COUNTER.labels(result="hit").inc()
            return data

        REMOTE_CONFIG_CACHE_COUNTER.labels(result="miss").inc()
        try:
            remote_config = cls.objects.select_related("team").get(team__api_token=token)
        except cls.DoesNotExist:
            # Try to find the team and create RemoteConfig if it exists
            try:
                from posthog.models.team import Team

                team = Team.objects.get(api_token=token)
                remote_config = cls(team=team)  # type: ignore[assignment]
            except Team.DoesNotExist:
                cache.set(key, "404", timeout=CACHE_TIMEOUT)
                REMOTE_CONFIG_CACHE_COUNTER.labels(result="miss_but_missing").inc()
                raise cls.DoesNotExist()

        data = remote_config.build_config()
        cache.set(key, data, timeout=CACHE_TIMEOUT)

        return data

    @classmethod
    def get_config_via_token(cls, token: str, request: Optional[HttpRequest] = None) -> dict:
        config = cls._get_config_via_cache(token)
        config = sanitize_config_for_public_cdn(config, request=request)

        return config

    @classmethod
    def get_config_js_via_token(cls, token: str, request: Optional[HttpRequest] = None) -> str:
        config = cls._get_config_via_cache(token)
        # Get the site apps JS so we can render it in the JS
        site_apps_js = config.pop("siteAppsJS", None)
        # We don't want to include the minimal site apps content as we have the JS now
        config.pop("siteApps", None)
        config = sanitize_config_for_public_cdn(config, request=request)

        js_content = f"""(function() {{
  window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {{}};
  window._POSTHOG_REMOTE_CONFIG['{token}'] = {{
    config: {json.dumps(config)},
    siteApps: [{",".join(site_apps_js)}]
  }}
}})();
        """.strip()

        return js_content

    @classmethod
    def get_array_js_via_token(cls, token: str, request: Optional[HttpRequest] = None) -> str:
        # NOTE: Unlike the other methods we dont store this in the cache as it is cheap to build at runtime
        js_content = cls.get_config_js_via_token(token, request=request)

        return f"""{get_array_js_content()}\n\n{js_content}"""

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

            # Update the redis cache key for the config
            cache.set(cache_key_for_team_token(self.team.api_token), config, timeout=CACHE_TIMEOUT)
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
            data["files"].append({"url": f"{full_domain}/array/{self.team.api_token}/array.js"})

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

    def __str__(self):
        return f"RemoteConfig {self.team_id}"


def _update_team_remote_config(team_id: int):
    from posthog.tasks.remote_config import update_team_remote_config

    update_team_remote_config.delay(team_id)


@receiver(pre_save, sender=Team)
def team_pre_save(sender, instance: "Team", **kwargs):
    """Capture old api_token value before save for cache cleanup."""
    from posthog.storage.team_access_cache_signal_handlers import capture_old_api_token

    capture_old_api_token(instance, **kwargs)


@receiver(post_save, sender=Team)
def team_saved(sender, instance: "Team", created, **kwargs):
    transaction.on_commit(lambda: _update_team_remote_config(instance.id))

    from posthog.storage.team_access_cache_signal_handlers import update_team_authentication_cache

    transaction.on_commit(lambda: update_team_authentication_cache(instance, created, **kwargs))


@receiver(post_delete, sender=Team)
def team_deleted(sender, instance: "Team", **kwargs):
    """Handle team deletion for access cache."""
    from posthog.storage.team_access_cache_signal_handlers import update_team_authentication_cache_on_delete

    transaction.on_commit(lambda: update_team_authentication_cache_on_delete(instance, **kwargs))


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
def site_function_saved(sender, instance: "HogFunction", created, **kwargs):
    if instance.enabled and instance.type in ("site_destination", "site_app"):
        transaction.on_commit(lambda: _update_team_remote_config(instance.team_id))


@receiver(post_save, sender=Survey)
def survey_saved(sender, instance: "Survey", created, **kwargs):
    transaction.on_commit(lambda: _update_team_remote_config(instance.team_id))


@receiver(post_save, sender=ErrorTrackingSuppressionRule)
def error_tracking_suppression_rule_saved(sender, instance: "ErrorTrackingSuppressionRule", created, **kwargs):
    transaction.on_commit(lambda: _update_team_remote_config(instance.team_id))


@receiver(post_save, sender=PersonalAPIKey)
def personal_api_key_saved(sender, instance: "PersonalAPIKey", created, **kwargs):
    """
    Handle PersonalAPIKey save for team access cache invalidation.

    Skip cache updates for last_used_at field updates to avoid unnecessary cache warming
    during authentication requests.
    """
    from posthog.storage.team_access_cache_signal_handlers import update_personal_api_key_authentication_cache

    # Skip cache updates if only last_used_at is being updated
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and set(update_fields) == {"last_used_at"}:
        return

    transaction.on_commit(lambda: update_personal_api_key_authentication_cache(instance))


@receiver(post_delete, sender=PersonalAPIKey)
def personal_api_key_deleted(sender, instance: "PersonalAPIKey", **kwargs):
    """
    Handle PersonalAPIKey delete for team access cache invalidation.
    """
    from posthog.storage.team_access_cache_signal_handlers import update_personal_api_key_deleted_cache

    transaction.on_commit(lambda: update_personal_api_key_deleted_cache(instance))


@receiver(post_save, sender=User)
def user_saved(sender, instance: "User", created, **kwargs):
    """
    Handle User save for team access cache updates when is_active changes.

    When a user's is_active status changes, their Personal API Keys need to be
    added or removed from team authentication caches.
    """
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "is_active" not in update_fields:
        logger.debug(f"User {instance.id} updated but is_active unchanged, skipping cache update")
        return

    # If update_fields is None, we need to update cache since all fields (including is_active) might have changed

    from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

    transaction.on_commit(lambda: update_user_authentication_cache(instance, **kwargs))


@receiver(post_save, sender=OrganizationMembership)
def organization_membership_saved(sender, instance: "OrganizationMembership", created, **kwargs):
    """
    Handle OrganizationMembership creation for team access cache updates.

    When a user is added to an organization, their unscoped personal API keys
    should gain access to teams within that organization. This ensures
    that the authentication cache is updated to reflect the new access rights.

    Note: We intentionally only handle creation (created=True), not updates.
    Changes to membership level (e.g., MEMBER → ADMIN) don't affect API key
    access - Personal API keys grant access based on organization membership
    existence, not role level.
    """
    if created:
        from posthog.storage.team_access_cache_signal_handlers import update_organization_membership_created_cache

        transaction.on_commit(lambda: update_organization_membership_created_cache(instance))


@receiver(post_delete, sender=OrganizationMembership)
def organization_membership_deleted(sender, instance: "OrganizationMembership", **kwargs):
    """
    Handle OrganizationMembership deletion for team access cache invalidation.

    When a user is removed from an organization, their unscoped personal API keys
    should no longer have access to teams within that organization. This ensures
    that the authentication cache is updated to reflect the change in access rights.
    """
    from posthog.storage.team_access_cache_signal_handlers import update_organization_membership_deleted_cache

    transaction.on_commit(lambda: update_organization_membership_deleted_cache(instance))
