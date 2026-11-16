from django.db import models

from posthog.models.utils import UUIDModel


class IdentityProviderEmailVerification(UUIDModel):
    """The user entered a code mailed to the address an identity provider asserted for one identity.

    Keyed by the provider's issuer and its subject (OIDC `sub`, SAML name ID) rather than by
    `IdentityProviderConfig` or by user: two configs can front the same IdP, but a second identity
    at that IdP has proved nothing, and a config repointed to a different IdP presents a different
    issuer, so neither inherits this row. `email` is the address the code was mailed to, so a
    changed assertion needs a new code.
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
    provider = models.CharField(
        max_length=32,
        help_text="SSO backend that issued the assertion, such as saml or oidc.",
    )
    issuer = models.CharField(
        max_length=512,
        help_text="OIDC issuer URL or SAML entity ID of the identity provider that asserted the address.",
    )
    subject = models.CharField(
        max_length=255,
        help_text="The identity provider's own identifier for the user, such as an OIDC sub or a SAML name ID.",
    )
    email = models.EmailField(
        max_length=254,
        help_text="The asserted address the code was mailed to. A different address needs a new code.",
    )
    verified_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the user entered the code emailed to the address the identity provider asserted.",
    )

    class Meta:
        verbose_name = "identity provider email verification"
        constraints = [
            models.UniqueConstraint(fields=["provider", "issuer", "subject"], name="unique_idp_email_verification"),
        ]

    def __str__(self) -> str:
        return f"{self.issuer} {self.subject}"
