from django.db import models

from posthog.models.utils import UUIDModel


class IdentityProviderEmailVerification(UUIDModel):
    """The user entered a code mailed to the address an identity provider asserted for them.

    Scoped by the provider's issuer rather than by `IdentityProviderConfig`: two configs can front
    the same IdP, so proving the address through one proves it for the other. A different issuer is
    a different IdP, and needs its own proof.
    """

    objects: models.Manager["IdentityProviderEmailVerification"]

    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        # `posthog_user` is read on nearly every request. A real constraint makes the CREATE TABLE
        # take a lock on it that queues behind in-flight queries, so the row is cleaned up in Python.
        db_constraint=False,
        related_name="identity_provider_email_verifications",
    )
    issuer = models.CharField(
        max_length=512,
        help_text="OIDC issuer URL or SAML entity ID of the identity provider that asserted the address.",
    )
    verified_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the user entered the code emailed to the address the identity provider asserted.",
    )

    class Meta:
        verbose_name = "identity provider email verification"
        constraints = [
            models.UniqueConstraint(fields=["user", "issuer"], name="unique_idp_email_verification"),
        ]

    def __str__(self) -> str:
        return self.issuer
