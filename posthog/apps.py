import os

import posthoganalytics
from django.apps import AppConfig
from django.conf import settings
from posthoganalytics.client import Client

from posthog.settings import SELF_CAPTURE, SKIP_ASYNC_MIGRATIONS_SETUP
from posthog.utils import get_git_branch, get_git_commit, get_machine_id, get_self_capture_api_token, print_warning
from posthog.version import VERSION


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        posthoganalytics.personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")

        if settings.TEST or os.environ.get("OPT_OUT_CAPTURE", False):
            posthoganalytics.disabled = True
        elif settings.DEBUG:
            # log development server launch to posthog
            if os.getenv("RUN_MAIN") == "true":
                # Sync all organization.available_features once on launch, in case plans changed
                from posthog.celery import sync_all_organization_available_features

                sync_all_organization_available_features()

                # NOTE: This has to be created as a separate client so that the "capture" call doesn't lock in the properties
                phcloud_client = Client(posthoganalytics.api_key)

                phcloud_client.capture(
                    get_machine_id(),
                    "development server launched",
                    {"posthog_version": VERSION, "git_rev": get_git_commit(), "git_branch": get_git_branch(),},
                )

            if SELF_CAPTURE:
                posthoganalytics.api_key = get_self_capture_api_token(None)
                posthoganalytics.host = settings.SITE_URL
            else:
                posthoganalytics.disabled = True

        if not settings.SKIP_SERVICE_VERSION_REQUIREMENTS:
            for service_version_requirement in settings.SERVICE_VERSION_REQUIREMENTS:
                in_range, version = service_version_requirement.is_service_in_accepted_version()
                if not in_range:
                    print(
                        f"\033[91mService {service_version_requirement.service} is in version {version}. Expected range: {str(service_version_requirement.supported_version)}. PostHog may not work correctly with the current version. To continue anyway, add SKIP_SERVICE_VERSION_REQUIREMENTS=1 as an environment variable\033[0m",
                    )
                    exit(1)

        from posthog.async_migrations.setup import setup_async_migrations

        if SKIP_ASYNC_MIGRATIONS_SETUP:
            print_warning(["Skipping async migrations setup. This is unsafe in production!"])
        else:
            setup_async_migrations()
