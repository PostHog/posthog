import os

# Django Imports
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.http.response import HttpResponse

# Structlog Import
import structlog

# PostHog OpenTelemetry Initialization
from posthog.otel_instrumentation import initialize_otel

os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
# Try to ensure SERVER_GATEWAY_INTERFACE is fresh for the child process
if "SERVER_GATEWAY_INTERFACE" in os.environ:
    del os.environ["SERVER_GATEWAY_INTERFACE"]  # Delete if inherited
os.environ["SERVER_GATEWAY_INTERFACE"] = "ASGI"  # Set definitively

initialize_otel()  # Initialize OpenTelemetry first

# Get a structlog logger for asgi.py's own messages
logger = structlog.get_logger(__name__)


# Django doesn't support lifetime requests and raises an exception
# when it receives them. This creates a lot of noise in error tracking so
# intercept these requests and return a 501 error without raising an exception
def lifetime_wrapper(func):
    async def inner(scope, receive, send):
        if scope["type"] != "http":
            return HttpResponse(status=501)
        return await func(scope, receive, send)

    return inner


# PostHogConfig.ready() handles setting the global analytics key in WSGI. The same code couldn't run
# in ASGI because ready() doesn't expose an async interface.
def self_capture_wrapper(func):
    if not settings.DEBUG or not settings.SELF_CAPTURE:
        return func

    async def inner(scope, receive, send):
        if (
            settings.IS_CONNECTED_TO_PROD_PG_IN_DEBUG
            and settings.DEBUG_LOG_IN_AS_EMAIL
            and not getattr(inner, "local_write_db_prod_synced", False)
        ):
            await _prep_local_db_for_prod_reads()
            inner.local_write_db_prod_synced = True  # type: ignore

        if not getattr(inner, "debug_analytics_initialized", False) and not settings.IS_CONNECTED_TO_PROD_PG_IN_DEBUG:
            from posthog.utils import initialize_self_capture_api_token

            await initialize_self_capture_api_token()
            # Set a flag to indicate that the analytics key has been set, so we don't run the code on every request.
            inner.debug_analytics_initialized = True  # type: ignore
        return await func(scope, receive, send)

    return inner


async def _prep_local_db_for_prod_reads():
    """
    When connecting to the prod DB locally, we need foreign keys associated with the user we're impersonating to exist locally.

    Rationale:
    If we don't ensure this, then we can't use the local DB for any writes. An example is the AI Conversation model:
    for a Conversation to be started, it needs to be persisted. We can't do this in the prod DB, as we're only reading it,
    so we must persist the Conversation locally. For that local write to work, the `team_id` and `user_id` foreign keys
    must resolve in the local DB _as well_ as in the prod one!
    """
    from posthog.models import Organization, Project, Team, User

    user: User = await User.objects.aget(email=settings.DEBUG_LOG_IN_AS_EMAIL)
    try:
        await User.objects.using("default").acreate(email=settings.DEBUG_LOG_IN_AS_EMAIL, id=user.id)
    except Exception:
        pass
    if not user.current_organization_id:
        raise ValueError(f"User {user.email} has no current organization")
    if not user.current_team_id:
        raise ValueError(f"User {user.email} has no current team")
    try:
        await Organization.objects.using("default").acreate(
            name=f"Placeholder for {settings.DEBUG_LOG_IN_AS_EMAIL}",
            id=user.current_organization_id,
            slug=user.current_organization_id,
        )
    except Exception:
        pass
    try:
        await Project.objects.using("default").acreate(
            name=f"Placeholder for {settings.DEBUG_LOG_IN_AS_EMAIL}",
            id=user.current_team_id,
            organization_id=user.current_organization_id,
        )
    except Exception:
        pass
    try:
        await Team.objects.using("default").acreate(
            name=f"Placeholder for {settings.DEBUG_LOG_IN_AS_EMAIL}",
            id=user.current_team_id,
            project_id=user.current_team_id,
            organization_id=user.current_organization_id,
        )
    except Exception:
        pass


application = lifetime_wrapper(self_capture_wrapper(get_asgi_application()))
