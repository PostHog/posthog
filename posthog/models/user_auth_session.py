from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


class UserAuthSession(UUIDModel):
    """Queryable index of a user's active cookie-auth login sessions.

    Django stores the authenticated user only inside the encoded session blob, which can't be
    queried per user. This table mirrors the session key alongside the user and request metadata
    so users can see where they're logged in and revoke a session remotely. It is not a foreign
    key to `django_session`: `login()` rotates the key (`cycle_key`) and the session machinery
    owns row lifecycle, so we mirror the key and reconcile via GC instead of cascading.

    Impersonation sessions are deliberately never recorded here — the activity middleware skips
    them — so a staff member impersonating a customer never appears in the customer's own list.
    """

    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="auth_sessions")
    session_key = models.CharField(max_length=40, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_activity = models.DateTimeField(default=timezone.now)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    short_user_agent = models.CharField(max_length=255, null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    login_method = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-last_activity"])]
