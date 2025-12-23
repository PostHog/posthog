import os

import django
from django.conf import settings

# setup PostHog Django Project
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

# Skip the self-capture API token initialization during app.ready()
# This prevents hanging during database connection in app.ready()
# We initialize self-capture after django.setup() completes
os.environ["SERVER_GATEWAY_INTERFACE"] = "ASGI"

django.setup()

# Initialize self-capture for Dagster so we can use posthoganalytics
if settings.DEBUG and settings.SELF_CAPTURE:
    import asyncio

    from posthog.utils import initialize_self_capture_api_token

    asyncio.get_event_loop().run_until_complete(initialize_self_capture_api_token())
