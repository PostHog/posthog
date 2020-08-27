import hashlib
import os
import uuid

import posthoganalytics
from django.apps import AppConfig
from django.conf import settings


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"
        if settings.DEBUG:
            # log development server launch to posthog
            if os.getenv("RUN_MAIN") == "true":
                # MAC addresses are 6 bits long, so overflow shouldn't happen
                # hashing here as we don't care about the actual address, just it being rather consistent
                mac_address_hash = hashlib.md5(uuid.getnode().to_bytes(6, "little")).hexdigest()
                posthoganalytics.capture(mac_address_hash, "development server launched")
            posthoganalytics.disabled = True
        elif settings.TEST or os.environ.get("OPT_OUT_CAPTURE"):
            posthoganalytics.disabled = True
