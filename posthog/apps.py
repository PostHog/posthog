import os

from django.apps import AppConfig
from django.conf import settings

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from posthoganalytics.client import Client

from posthog.git import get_git_branch, get_git_commit_short
from posthog.tasks.tasks import sync_all_organization_available_product_features
from posthog.utils import get_instance_region, get_machine_id, initialize_self_capture_api_token

logger = structlog.get_logger(__name__)


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        self._setup_lazy_admin()
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        posthoganalytics.personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")
        posthoganalytics.poll_interval = 90
        posthoganalytics.enable_exception_autocapture = True
        posthoganalytics.log_captured_exceptions = True
        posthoganalytics.super_properties = {
            "region": get_instance_region(),
            "service": settings.OTEL_SERVICE_NAME,
            "environment": os.getenv("SENTRY_ENVIRONMENT"),
        }

        if settings.E2E_TESTING:
            posthoganalytics.api_key = "phc_ex7Mnvi4DqeB6xSQoXU1UVPzAmUIpiciRKQQXGGTYQO"
            posthoganalytics.personal_api_key = None
        elif settings.TEST or os.environ.get("OPT_OUT_CAPTURE", False):
            posthoganalytics.disabled = True
        elif settings.DEBUG:
            # In dev, analytics is by default turned to self-capture, i.e. data going into this very instance of PostHog
            # Due to ASGI's workings, we can't query for the right project API key in this `ready()` method
            # Instead, we configure self-capture with `self_capture_wrapper()` in posthog/asgi.py - see that file
            # Self-capture for WSGI is initialized here
            posthoganalytics.disabled = True
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
        # load feature flag definitions if not already loaded
        if not posthoganalytics.disabled and posthoganalytics.feature_flag_definitions() is None:
            posthoganalytics.load_feature_flags()

        from posthog.async_migrations.setup import setup_async_migrations

        if settings.SKIP_ASYNC_MIGRATIONS_SETUP:
            logger.warning("Skipping async migrations setup. This is unsafe in production!")
        else:
            setup_async_migrations()

        from posthog.tasks.hog_functions import queue_sync_hog_function_templates

        # Skip during tests since we handle this in conftest.py
        if not settings.TEST:
            queue_sync_hog_function_templates()

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
