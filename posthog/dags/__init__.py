import os

import django

# setup PostHog Django Project
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

# Skip the self-capture API token initialization for Dagster
# This prevents hanging during database connection in app.ready()
os.environ["SERVER_GATEWAY_INTERFACE"] = "ASGI"

django.setup()
