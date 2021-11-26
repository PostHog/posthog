import os

import posthoganalytics
from django.apps import AppConfig
from django.conf import settings

from posthog.tasks.status_report import get_instance_licenses
from posthog.utils import get_git_branch, get_git_commit, get_helm_info_env, get_instance_realm, get_machine_id
from posthog.version import VERSION


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        posthoganalytics.personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")

        if settings.DEBUG:
            # log development server launch to posthog
            if os.getenv("RUN_MAIN") == "true":
                # Sync all organization.available_features once on launch, in case plans changed
                from posthog.celery import sync_all_organization_available_features

                sync_all_organization_available_features()

                posthoganalytics.capture(
                    get_machine_id(),
                    "development server launched",
                    {"posthog_version": VERSION, "git_rev": get_git_commit(), "git_branch": get_git_branch(),},
                )
            posthoganalytics.disabled = True
        elif settings.TEST or os.environ.get("OPT_OUT_CAPTURE", False):
            posthoganalytics.disabled = True
        else:
            instance_properties = {
                "posthog_version": VERSION,
                "deployment": os.getenv("DEPLOYMENT", "unknown"),
                "realm": get_instance_realm(),
                "site_url": settings.SITE_URL,
                "license_keys": get_instance_licenses(),
                "helm": get_helm_info_env(),
            }
            posthoganalytics.capture(
                get_machine_id(), "server launched", instance_properties, groups={"instance": settings.SITE_URL}
            )
            posthoganalytics.group_identify("instance", settings.SITE_URL, instance_properties)

        if not settings.SKIP_SERVICE_VERSION_REQUIREMENTS:
            for service_version_requirement in settings.SERVICE_VERSION_REQUIREMENTS:
                [in_range, version] = service_version_requirement.is_service_in_accepted_version()
                if not in_range:
                    start_anyway = input(
                        f"Service {service_version_requirement.service} is in version {version}. Expected range: {str(service_version_requirement.supported_version)}. PostHog may not work correctly with the current version. Continue? [y/n]"
                    )
                    if start_anyway.lower() != "y":
                        print(f"Unsupported version for service {service_version_requirement.service}, exiting...")
                        exit(1)
