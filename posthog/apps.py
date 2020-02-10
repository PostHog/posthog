from django.apps import AppConfig
import posthoganalytics # type: ignore


class PostHogConfig(AppConfig):
    name = 'posthog'
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = 'sTMFPsFhdP1Ssg'
        posthoganalytics.host = 'http://127.0.0.1:8000'