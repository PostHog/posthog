from django.contrib.sessions.base_session import AbstractBaseSession
from django.db import models


class Session(AbstractBaseSession):
    """The application's session model, stored on the `django_session` table.

    Subclasses Django's `AbstractBaseSession` and is wired in via `SESSION_ENGINE`
    (`posthog.session.backend`). Beyond the base columns (`session_key`, `session_data`,
    `expire_date`) it adds a queryable `user_id` plus best-effort display metadata so a user can
    see where they're logged in and revoke a session remotely.

    `user_id` is stamped by the store from the session's `_auth_user_id` on every save, so it stays
    in sync with the authenticated user with no separate index table. Impersonation sessions are
    never attributed to the impersonated user (the store leaves `user_id` NULL for them).

    Reusing the existing `django_session` table — rather than a new one — is deliberate: swapping the
    engine then logs nobody out, since existing cookies decode unchanged.
    """

    # Plain BigIntegerField, not a ForeignKey to posthog_user: avoids a per-write FK constraint
    # check against the user table on this every-request-written table (performance).
    user_id = models.BigIntegerField(null=True)
    last_activity = models.DateTimeField(null=True)
    ip = models.GenericIPAddressField(null=True)
    short_user_agent = models.CharField(max_length=255, null=True)
    location = models.CharField(max_length=255, null=True)
    login_method = models.CharField(max_length=64, null=True)

    class Meta:
        db_table = "django_session"
        indexes = [models.Index(fields=["user_id"], name="django_session_user_id_idx")]

    @classmethod
    def get_session_store_class(cls):
        from posthog.session.backend import SessionStore

        return SessionStore
