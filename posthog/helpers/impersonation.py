from datetime import timedelta

from django.contrib.auth import (
    get_user as auth_get_user,
    get_user_model,
)
from django.core.signing import TimestampSigner

from loginas import settings as la_settings
from loginas.utils import is_impersonated_session


def get_original_user_from_session(request):
    """Extract the original staff user from an impersonated session."""
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


def get_impersonated_user(request):
    """Return the user being impersonated, looked up from the session.

    Reads from the session (not `request.user`) so callers get the right user even
    after `AdminImpersonationMiddleware` has swapped `request.user` to the original
    staff user on `/admin/` paths.
    """
    if not is_impersonated_session(request):
        return None
    user = auth_get_user(request)
    return user if user.is_authenticated else None


def impersonation_context(request):
    """Template context processor exposing the impersonated user for admin templates."""
    return {"impersonated_user": get_impersonated_user(request)}
