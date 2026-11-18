from django.db import models

from posthog.models.utils import UUIDModel


class IdentityProviderEmailVerification(UUIDModel):
    """Account-mailbox approval for an identity provider's issuer, subject, and asserted address.

    A linked identity can survive a provider replacement or account email change, so its new
    proof must come from the account mailbox. SAML includes the signing certificate fingerprint
    in the issuer so a replacement provider cannot reuse an earlier approval.
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
        help_text="OIDC issuer URL, or fingerprint of the SAML entity ID and signing certificate.",
    )
    subject = models.CharField(
        max_length=255,
        help_text="The identity provider's own identifier for the user, such as an OIDC sub or a SAML name ID.",
    )
    email = models.EmailField(
        max_length=254,
        help_text="The asserted address approved by the mailbox owner. A different address needs a new code.",
    )
    target_email = models.EmailField(
        max_length=254,
        help_text="The account mailbox that approved this identity. A different mailbox needs a new code.",
    )
    verified_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the mailbox owner approved this identity by entering an emailed code.",
    )

    class Meta:
        verbose_name = "identity provider email verification"
        constraints = [
            models.UniqueConstraint(fields=["provider", "issuer", "subject"], name="unique_idp_email_verification"),
        ]

    def __str__(self) -> str:
        return f"{self.issuer} {self.subject}"
