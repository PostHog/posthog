import os
import sys

import posthoganalytics
from django.apps import AppConfig
from django.conf import settings

from posthog.utils import get_git_branch, get_git_commit, get_machine_id
from posthog.version import VERSION


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        posthoganalytics.personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")

        # Skip plugin sync in manage.py scripts and in tests
        # (the database tables might not yet be created)
        if (
            not settings.TEST
            and not "makemigrations" in sys.argv
            and not "migrate" in sys.argv
            and not "manage.py" in sys.argv
            and not "/mypy" in sys.argv[0]
        ):
            from posthog.plugins import sync_plugin_config

            # syncs posthog.json['plugins'] and the Plugin/PluginConfig models
            sync_plugin_config()

        if settings.DEBUG:
            # log development server launch to posthog
            if os.getenv("RUN_MAIN") == "true":
                posthoganalytics.capture(
                    get_machine_id(),
                    "development server launched",
                    {"posthog_version": VERSION, "git_rev": get_git_commit(), "git_branch": get_git_branch(),},
                )
            posthoganalytics.disabled = True
        elif settings.TEST or os.environ.get("OPT_OUT_CAPTURE"):
            posthoganalytics.disabled = True
