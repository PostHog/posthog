import os

import posthoganalytics
import structlog
from asgiref.sync import async_to_sync
from django.apps import AppConfig
from django.conf import settings
from posthoganalytics.client import Client

from posthog.git import get_git_branch, get_git_commit_short
from posthog.tasks.tasks import sync_all_organization_available_product_features
from posthog.utils import get_machine_id, initialize_self_capture_api_token, get_instance_region


logger = structlog.get_logger(__name__)


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        posthoganalytics.personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")
        posthoganalytics.poll_interval = 90
        posthoganalytics.enable_exception_autocapture = True
        posthoganalytics.log_captured_exceptions = True
        posthoganalytics.super_properties = {"region": get_instance_region()}

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
