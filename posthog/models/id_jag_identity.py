from django.db import models

from posthog.models.utils import UUIDModel

IDENTITY_FIELD_MAX_LENGTH = 255


class IdJagIdentity(UUIDModel):
    """Binds an IdP subject to the PostHog user it was first matched to by email.

    Later ID-JAGs resolve the user by subject, so an IdP-side email change keeps the same
    account, and an email address the IdP gives to a different person reaches no account.
    """

    # db_index=False: both unique constraints lead with this column and serve its lookups.
    identity_provider_config = models.ForeignKey(
        "posthog.IdentityProviderConfig", on_delete=models.CASCADE, related_name="id_jag_identities", db_index=False
    )
    # The verified `iss`. Subjects are unique only within one issuer, so a link made under an
    # issuer the configuration no longer names must not resolve tokens from its replacement.
    issuer = models.CharField(max_length=512)
    # The draft's `tenant` claim, set by IdPs that issue for several tenants under one `iss`.
    tenant = models.CharField(max_length=IDENTITY_FIELD_MAX_LENGTH, blank=True, default="")
    subject = models.CharField(max_length=IDENTITY_FIELD_MAX_LENGTH)
    # db_constraint=False: posthog_user is a hot table, see safe-django-migrations.md.
    user = models.ForeignKey(
        "posthog.User", on_delete=models.CASCADE, db_constraint=False, related_name="id_jag_identities"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("identity_provider_config", "issuer", "tenant", "subject"),
                name="unique_id_jag_identity_subject",
            ),
            models.UniqueConstraint(
                fields=("identity_provider_config", "issuer", "user"),
                name="unique_id_jag_identity_user",
            ),
        ]
