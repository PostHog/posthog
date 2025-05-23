"""
WSGI config for posthog project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

import os

# PostHog OpenTelemetry Initialization
from posthog.otel_instrumentation import initialize_otel

from django.core.wsgi import get_wsgi_application

initialize_otel()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("SERVER_GATEWAY_INTERFACE", "WSGI")

application = get_wsgi_application()
