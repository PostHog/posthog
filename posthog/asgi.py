import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("SERVER_GATEWAY_INTERFACE", "ASGI")

application = get_asgi_application()
