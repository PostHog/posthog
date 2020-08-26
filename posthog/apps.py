import os

import posthoganalytics
from django.apps import AppConfig
from django.conf import settings


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        if settings.DEBUG:
            if os.getenv("RUN_MAIN") == "true":
                first_team = self.get_model("Team").objects.first()
                if first_team is not None:
                    first_user = first_team.users.first()
                    if first_user is not None:
                        posthoganalytics.capture(first_user.distinct_id, "development server launched")
            posthoganalytics.disabled = True
        elif settings.TEST or os.environ.get("OPT_OUT_CAPTURE"):
            posthoganalytics.disabled = True
