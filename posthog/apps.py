import os

import posthoganalytics
from django.apps import AppConfig
from django.conf import settings

from posthog.utils import get_machine_id


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        if settings.DEBUG:
            # log development server launch to posthog
            if os.getenv("RUN_MAIN") == "true":
                posthoganalytics.capture(get_machine_id(), "development server launched")
            posthoganalytics.disabled = True
        elif settings.TEST or os.environ.get("OPT_OUT_CAPTURE"):
            posthoganalytics.disabled = True
