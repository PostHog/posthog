import os

from django.apps import AppConfig
from django.conf import settings

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from posthoganalytics.client import Client

from posthog.git import get_git_branch, get_git_commit_short
from posthog.tasks.tasks import sync_all_organization_available_product_features
from posthog.utils import (
    get_available_timezones_with_offsets,
    get_instance_region,
    get_machine_id,
    initialize_self_capture_api_token,
    str_to_bool,
)

logger = structlog.get_logger(__name__)


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        import posthog.storage.team_access_cache_signal_handlers  # noqa: F401

        self._setup_lazy_admin()
        self._prewarm_timezone_offsets_cache()
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"  # ty: ignore[invalid-assignment]
        # Fall back to DEV_API_KEY in debug so feature flags work locally without manual env setup.
        # DEV_API_KEY lives in ee/settings.py — getattr returns None in OSS mode.
        posthoganalytics.personal_api_key = os.environ.get(
            "POSTHOG_PERSONAL_API_KEY",
            getattr(settings, "DEV_API_KEY", None) if settings.DEBUG else None,
        )
        posthoganalytics.poll_interval = 90  # ty: ignore[invalid-assignment]
        posthoganalytics.enable_exception_autocapture = True  # ty: ignore[invalid-assignment]
        posthoganalytics.log_captured_exceptions = True  # ty: ignore[invalid-assignment]
        posthoganalytics.super_properties = {  # ty: ignore[invalid-assignment]
            "region": get_instance_region(),
            "service": settings.OTEL_SERVICE_NAME,
            "environment": os.getenv("OTEL_SERVICE_ENVIRONMENT"),
        }

        if str_to_bool(os.environ.get("TEMPORAL_DISABLE_EXCEPTION_VARIABLE_CAPTURE", "false")):
            posthoganalytics.capture_exception_code_variables = False
        else:
            posthoganalytics.capture_exception_code_variables = True  # ty: ignore[invalid-assignment]

        if settings.E2E_TESTING:
            posthoganalytics.api_key = "phc_ex7Mnvi4DqeB6xSQoXU1UVPzAmUIpiciRKQQXGGTYQO"  # ty: ignore[invalid-assignment]
            posthoganalytics.personal_api_key = None
        elif settings.TEST or os.environ.get("OPT_OUT_CAPTURE", False):
            posthoganalytics.disabled = True  # ty: ignore[invalid-assignment]
        elif settings.DEBUG:
            # In dev, analytics is by default turned to self-capture, i.e. data going into this very instance of PostHog
            # Due to ASGI's workings, we can't query for the right project token in this `ready()` method
            # Instead, we configure self-capture with `self_capture_wrapper()` in posthog/asgi.py - see that file
            # Self-capture for WSGI is initialized here
            posthoganalytics.disabled = True  # ty: ignore[invalid-assignment]
            logger.info(
                "posthog_config_ready",
                settings_debug=settings.DEBUG,
                server_gateway_interface=settings.SERVER_GATEWAY_INTERFACE,
            )
            if settings.SERVER_GATEWAY_INTERFACE == "WSGI":
                async_to_sync(initialize_self_capture_api_token)()

            # log development server launch to posthog
            if os.getenv("RUN_MAIN") == "true":
                # Sync all organization.available_product_features once on launch, in case plans changed
                sync_all_organization_available_product_features()

                # NOTE: This has to be created as a separate client so that the "capture" call doesn't lock in the properties
                phcloud_client = Client(posthoganalytics.api_key)

                phcloud_client.capture(
                    distinct_id=get_machine_id(),
                    event="development server launched",
                    properties={"git_rev": get_git_commit_short(), "git_branch": get_git_branch()},
                )
        # Use HyperCache to provide flag definitions instead of per-process API polling.
        # Falls back to the SDK's emergency API fetch (via personal_api_key) only when
        # the cache is cold. In E2E testing personal_api_key is None, so a cold cache
        # will result in no flag definitions being loaded — which is acceptable there.
        if not posthoganalytics.disabled:
            from posthog.feature_flags.sdk_cache_provider import HyperCacheFlagProvider

            posthoganalytics.flag_definition_cache_provider = HyperCacheFlagProvider(  # ty: ignore[invalid-assignment]
                team_id=int(os.environ.get("POSTHOG_SELF_TEAM_ID", "2"))
            )

        # load feature flag definitions if not already loaded
        if not posthoganalytics.disabled and posthoganalytics.feature_flag_definitions() is None:
            posthoganalytics.load_feature_flags()

        from posthog.async_migrations.setup import setup_async_migrations

        if settings.SKIP_ASYNC_MIGRATIONS_SETUP:
            logger.warning("Skipping async migrations setup. This is unsafe in production!")
        else:
            setup_async_migrations()

        from posthog.api.file_system import registrations as file_system_registrations
        from posthog.tasks.hog_functions import queue_sync_hog_function_templates

        # Skip during tests since we handle this in conftest.py
        # Skip during collectstatic (STATIC_COLLECTION=1 in Dockerfile) — no Redis available at build time
        if not settings.TEST and not settings.STATIC_COLLECTION:
            queue_sync_hog_function_templates()

        file_system_registrations.register_core_file_system_types()

    def _prewarm_timezone_offsets_cache(self):
        # The pytz walk in get_available_timezones_with_offsets is hourly-cached but
        # the cache is per-process. Without pre-warming, every fresh pod pays ~580ms
        # on its first preflight (the home view). Run it once at startup so the cache
        # is hot before any request lands. Skip during tests / static collection where
        # this would just slow setup with no benefit.
        if settings.TEST or settings.STATIC_COLLECTION:
            return
        try:
            get_available_timezones_with_offsets()
        except Exception:
            logger.warning("prewarm_timezone_offsets_cache_failure", exc_info=True)

    def _setup_lazy_admin(self):
        """Set up lazy loading of admin classes to avoid importing all at startup."""
        import sys

        from django.contrib import admin

        class LazyAdminRegistry(dict):
            """Lazy admin registry that loads admin on first access."""

            _loaded = False

            def _ensure_loaded(self):
                if not self._loaded:
                    from posthog.admin import register_all_admin

                    self._loaded = True
                    register_all_admin()

            # Override only the essential methods that trigger loading
            def __getitem__(self, key):
                self._ensure_loaded()
                return super().__getitem__(key)

            def __iter__(self):
                self._ensure_loaded()
                return super().__iter__()

            def __len__(self):
                self._ensure_loaded()
                return super().__len__()

            def __contains__(self, key):
                self._ensure_loaded()
                return super().__contains__(key)

        # Don't use lazy loading in tests and migrations
        if not settings.TEST and "migrate" not in sys.argv and "test" not in sys.argv:
            admin.site._registry = LazyAdminRegistry()

        # Install the OAuth sidebar regrouping override eagerly. It must wrap
        # `get_app_list` before the first admin request — if it were installed
        # from inside `register_all_admin()` it would only land mid-call, after
        # the original method had already started executing.
        from posthog.admin import install_admin_app_list_overrides

        install_admin_app_list_overrides()
