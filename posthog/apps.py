from django.apps import AppConfig
from django.conf import settings
import posthoganalytics # type: ignore


class PostHogConfig(AppConfig):
    name = 'posthog'
    verbose_name = "PostHog"

    def ready(self):
        if not settings.TEST:
            posthoganalytics.api_key = 'sTMFPsFhdP1Ssg'