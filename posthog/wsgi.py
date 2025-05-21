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
# SERVER_GATEWAY_INTERFACE is set by the WSGI server (e.g. gunicorn)
# We don't need to set it here as we did for ASGI, Gunicorn will handle it.
# os.environ.setdefault("SERVER_GATEWAY_INTERFACE", "WSGI") # This line can be removed or kept, gunicorn will override.

application = get_wsgi_application()
