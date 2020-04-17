from django.apps import AppConfig
from django.conf import settings
import posthoganalytics


class PostHogConfig(AppConfig):
    name = 'posthog'
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = 'sTMFPsFhdP1Ssg'
        if settings.TEST:
            posthoganalytics.disabled = True