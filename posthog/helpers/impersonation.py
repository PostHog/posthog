from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.signing import TimestampSigner

from loginas import settings as la_settings


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
