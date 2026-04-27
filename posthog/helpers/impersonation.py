from datetime import timedelta

from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY, get_user_model, load_backend
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
    """Return the user being impersonated, looked up directly from the session.

    Reads `SESSION_KEY`/`BACKEND_SESSION_KEY` from the session (not `request.user`
    nor `request._cached_user`) so callers get the impersonated customer even after
    `AdminImpersonationMiddleware` has swapped both attributes to the original staff
    user on `/admin/` paths.
    """
    if not is_impersonated_session(request):
        return None
    try:
        user_id = request.session[SESSION_KEY]
        backend_path = request.session[BACKEND_SESSION_KEY]
    except KeyError:
        return None
    try:
        backend = load_backend(backend_path)
        return backend.get_user(user_id)
    except Exception:
        return None


def impersonation_context(request):
    """Template context processor exposing the impersonated user for admin templates.

    Only active for `/admin/` paths to avoid the per-render DB lookup
    `auth_get_user` performs on every other view.
    """
    if not getattr(request, "path", "").startswith("/admin/"):
        return {}
    return {"impersonated_user": get_impersonated_user(request)}
