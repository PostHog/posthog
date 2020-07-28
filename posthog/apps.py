import os

import posthoganalytics
from django.apps import AppConfig
from django.conf import settings


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        if settings.TEST or os.environ.get("OPT_OUT_CAPTURE"):
            posthoganalytics.disabled = True
