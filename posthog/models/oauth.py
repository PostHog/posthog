from oauth2_provider.models import (
    AbstractAccessToken,
    AbstractIDToken,
    AbstractRefreshToken,
    AbstractGrant,
    AbstractApplication,
)

from posthog.models.utils import UUIDT, UUIDModel

from django.db import models


class OAuthApplication(AbstractApplication, UUIDModel):
    class Meta(AbstractApplication.Meta):
        verbose_name = "OAuth Application"
        verbose_name_plural = "OAuth Applications"
        swappable = "OAUTH2_PROVIDER_APPLICATION_MODEL"
        constraints = [
            models.CheckConstraint(
                check=models.Q(skip_authorization=False),
                name="enforce_skip_authorization_false",
            )
        ]

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    # Note: We do not require an organization or user to be linked to an OAuth application - this is so that we can support dynamic client registration
    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE, null=True, blank=True)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, null=True, blank=True)

    # Note: We do not support HS256 since we don't want to store the client secret in plaintext
    algorithm = models.CharField(
        max_length=255,
        choices=[
            ("RS256", "RSA with SHA-2 256"),
        ],
    )

    authorization_grant_type = models.CharField(
        max_length=255,
        choices=[
            (AbstractApplication.GRANT_AUTHORIZATION_CODE, "Authorization code"),
        ],
    )


class OAuthAccessToken(AbstractAccessToken, UUIDModel):
    class Meta(AbstractAccessToken.Meta):
        verbose_name = "OAuth Access Token"
        verbose_name_plural = "OAuth Access Tokens"
        swappable = "OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)


class OAuthIDToken(AbstractIDToken, UUIDModel):
    class Meta(AbstractIDToken.Meta):
        verbose_name = "OAuth ID Token"
        verbose_name_plural = "OAuth ID Tokens"
        swappable = "OAUTH2_PROVIDER_ID_TOKEN_MODEL"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)


class OAuthRefreshToken(AbstractRefreshToken, UUIDModel):
    class Meta(AbstractRefreshToken.Meta):
        verbose_name = "OAuth Refresh Token"
        verbose_name_plural = "OAuth Refresh Tokens"
        swappable = "OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)


class OAuthGrant(AbstractGrant, UUIDModel):
    class Meta(AbstractGrant.Meta):
        verbose_name = "OAuth Grant"
        verbose_name_plural = "OAuth Grants"
        swappable = "OAUTH2_PROVIDER_GRANT_MODEL"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)
    code_challenge_method = models.CharField(
        max_length=255,
        choices=[
            (AbstractGrant.CODE_CHALLENGE_S256, "SHA-256"),
        ],
    )
