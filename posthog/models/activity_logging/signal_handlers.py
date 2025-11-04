import inspect
import dataclasses
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.core.signing import TimestampSigner
from django.dispatch import receiver
from django.http import HttpRequest

import structlog
from loginas import settings as la_settings
from loginas.utils import is_impersonated_session

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.utils import get_ip_address, get_short_user_agent

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class UserLoginContext(ActivityContextBase):
    login_method: str
    ip_address: str
    user_agent: str
    reauth: bool


@dataclasses.dataclass(frozen=True)
class UserLogoutContext(ActivityContextBase):
    ip_address: str
    user_agent: str


def _get_original_user_from_session(request):
    """Extract the original admin user from the impersonation session."""
    try:
        signer = TimestampSigner()
        original_session = request.session.get(la_settings.USER_SESSION_FLAG)
        original_user_pk = signer.unsign(
            original_session, max_age=timedelta(days=la_settings.USER_SESSION_DAYS_TIMESTAMP)
        )
        User = get_user_model()
        return User.objects.get(pk=original_user_pk)
    except Exception:
        return None


def _get_logout_user_context(user, request):
    """Determine the correct user context and attribution for logout activity logging."""
    was_impersonated = is_impersonated_session(request)
    log_user = user
    item_id = str(user.id)

    if was_impersonated and hasattr(request, "session") and request.session:
        admin_user = _get_original_user_from_session(request)
        if admin_user:
            log_user = admin_user
            item_id = str(user.id)

    return was_impersonated, log_user, item_id


def _detect_impersonation_for_login(user, request):
    """Detect impersonation context for login events using stack inspection and session state."""
    has_impersonation_session = (
        hasattr(request, "session") and request.session and la_settings.USER_SESSION_FLAG in request.session
    )

    for frame in inspect.stack():
        if "loginas" in frame.filename:
            try:
                if "original_user_pk" in frame.frame.f_locals:
                    User = get_user_model()
                    original_user_pk = frame.frame.f_locals["original_user_pk"]
                    admin_user = User.objects.get(pk=original_user_pk)
                    return True, admin_user, str(user.id), "impersonation"
            except Exception:
                pass

            return True, user, str(user.id), "impersonation"

    if has_impersonation_session:
        try:
            original_user_pk = TimestampSigner().unsign(
                request.session.get(la_settings.USER_SESSION_FLAG),
                max_age=timedelta(days=la_settings.USER_SESSION_DAYS_TIMESTAMP),
            )
            User = get_user_model()
            admin_user = User.objects.get(pk=original_user_pk)
            return True, admin_user, str(user.id), "impersonation"
        except Exception:
            pass

    return False, user, str(user.id), "normal"


def _determine_login_method(request, was_impersonated, user):
    """Determine the login method based on the request and impersonation status."""

    login_method = "email_password"

    if was_impersonated:
        login_method = "impersonation"
    elif hasattr(request, "session") and request.session:
        backend = None
        for key in ["backend", "social_auth_last_login_backend", "partial_pipeline_backend"]:
            if key in request.session:
                backend = request.session[key]
                break

        if backend:
            backend_lower = backend.lower()
            if "github" in backend_lower:
                login_method = "github_sso"
            elif "gitlab" in backend_lower:
                login_method = "gitlab_sso"
            elif "google" in backend_lower:
                login_method = "google_sso"
            elif "saml" in backend_lower:
                login_method = "saml"
            else:
                login_method = "sso"
        else:
            if user.social_auth.exists():
                providers = list(user.social_auth.values_list("provider", flat=True))
                most_recent_provider = providers[-1].lower() if providers else ""
                if "github" in most_recent_provider:
                    login_method = "github_sso"
                elif "gitlab" in most_recent_provider:
                    login_method = "gitlab_sso"
                elif "google" in most_recent_provider:
                    login_method = "google_sso"
                else:
                    login_method = "sso"

    return login_method


@receiver(user_logged_in)
def log_user_login_activity(sender, user, request: HttpRequest, **kwargs):  # noqa: ARG001
    try:
        was_impersonated, log_user, item_id, _ = _detect_impersonation_for_login(user, request)
        ip_address = get_ip_address(request)
        user_agent = get_short_user_agent(request)
        reauth = request.session.get("reauth") == "true"

        organization_id = user.current_organization_id

        if organization_id is None:
            logger.info("Skipping login activity log - user has no organization", user_id=user.id)
            return

        log_activity(
            organization_id=organization_id,
            team_id=None,
            user=log_user,
            item_id=item_id,
            scope="User",
            activity="logged_in",
            detail=Detail(
                name=user.email,
                changes=[],
                context=UserLoginContext(
                    login_method=_determine_login_method(request, was_impersonated, user),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    reauth=reauth,
                ),
            ),
            was_impersonated=was_impersonated,
        )
    except Exception as e:
        logger.exception("Failed to log user login activity", user_id=user.id, error=e)
        capture_exception(e)


@receiver(user_logged_out)
def log_user_logout_activity(sender, user, request: HttpRequest, **kwargs):  # noqa: ARG001
    if not user:
        return

    try:
        was_impersonated, log_user, item_id = _get_logout_user_context(user, request)

        ip_address = get_ip_address(request)
        user_agent = get_short_user_agent(request)

        organization_id = user.current_organization_id

        if organization_id is None:
            logger.info("Skipping logout activity log - user has no organization", user_id=user.id)
            return

        log_activity(
            organization_id=organization_id,
            team_id=None,
            user=log_user,
            item_id=item_id,
            scope="User",
            activity="logged_out",
            detail=Detail(
                name=user.email,
                changes=[],
                context=UserLogoutContext(
                    ip_address=ip_address,
                    user_agent=user_agent,
                ),
            ),
            was_impersonated=was_impersonated,
        )
    except Exception as e:
        logger.exception("Failed to log user logout activity", user_id=user.id, error=e)
        capture_exception(e)
