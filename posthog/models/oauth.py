import enum
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models

from oauth2_provider.models import (
    AbstractAccessToken,
    AbstractApplication,
    AbstractGrant,
    AbstractIDToken,
    AbstractRefreshToken,
)

from posthog.models.utils import UUIDT


class OAuthApplicationAccessLevel(enum.Enum):
    ALL = "all"
    ORGANIZATION = "organization"
    TEAM = "team"


class OAuthApplication(AbstractApplication):
    class Meta(AbstractApplication.Meta):
        verbose_name = "OAuth Application"
        verbose_name_plural = "OAuth Applications"
        swappable = "OAUTH2_PROVIDER_APPLICATION_MODEL"
        constraints = [
            models.CheckConstraint(
                check=models.Q(skip_authorization=False),
                name="enforce_skip_authorization_false",
            ),
            # Note: We do not support HS256 since we don't want to store the client secret in plaintext
            models.CheckConstraint(check=models.Q(algorithm="RS256"), name="enforce_rs256_algorithm"),
            models.CheckConstraint(
                check=models.Q(authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE),
                name="enforce_supported_grant_types",
            ),
        ]

    def clean(self):
        super().clean()

        allowed_schemes = ["http", "https"] if settings.DEBUG else ["https"]

        for uri in self.redirect_uris.split(" "):
            if not uri:
                continue

            parsed_uri = urlparse(uri)

            if parsed_uri.scheme not in allowed_schemes:
                raise ValidationError(
                    {
                        "redirect_uris": f"Redirect URI {uri} must start with one of the following schemes: {', '.join(allowed_schemes)}"
                    }
                )

            if not parsed_uri.netloc:
                raise ValidationError({"redirect_uris": f"Redirect URI {uri} must contain a host"})

            # Note: URI fragments are not allowed in redirect URIs in the OAuth 2.0 specification
            if parsed_uri.fragment:
                raise ValidationError({"redirect_uris": f"Redirect URI {uri} cannot contain fragments"})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)
    # NOTE: By default an application should be linked to the organization that created it.
    # It can be null if the organization that created it is deleted, or it was created outside of an organization (e.g. using dynamic client registration)
    # Only admins of the organization should have permission to edit the application.
    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="oauth_applications"
    )

    # NOTE: The user that created the application. It should not be used to check for access to the application, since the user might have left the organization.
    user: models.ForeignKey = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)


class OAuthAccessToken(AbstractAccessToken):
    class Meta(AbstractAccessToken.Meta):
        verbose_name = "OAuth Access Token"
        verbose_name_plural = "OAuth Access Tokens"
        swappable = "OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    user: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="oauth_access_tokens",
    )

    scoped_teams: ArrayField = ArrayField(models.IntegerField(), null=True, blank=True)
    scoped_organizations: ArrayField = ArrayField(models.CharField(max_length=100), null=True, blank=True)


class OAuthIDToken(AbstractIDToken):
    class Meta(AbstractIDToken.Meta):
        verbose_name = "OAuth ID Token"
        verbose_name_plural = "OAuth ID Tokens"
        swappable = "OAUTH2_PROVIDER_ID_TOKEN_MODEL"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    user: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="oauth_id_tokens",
    )


class OAuthRefreshToken(AbstractRefreshToken):
    class Meta(AbstractRefreshToken.Meta):
        verbose_name = "OAuth Refresh Token"
        verbose_name_plural = "OAuth Refresh Tokens"
        swappable = "OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    user: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="oauth_refresh_tokens",
    )

    scoped_teams: ArrayField = ArrayField(models.IntegerField(), null=True, blank=True)
    scoped_organizations: ArrayField = ArrayField(models.CharField(max_length=100), null=True, blank=True)


class OAuthGrant(AbstractGrant):
    class Meta(AbstractGrant.Meta):
        verbose_name = "OAuth Grant"
        verbose_name_plural = "OAuth Grants"
        swappable = "OAUTH2_PROVIDER_GRANT_MODEL"

        # Note: We do not support plaintext code challenge methods since they are not secure
        constraints = [
            models.CheckConstraint(
                check=models.Q(code_challenge_method=AbstractGrant.CODE_CHALLENGE_S256),
                name="enforce_supported_code_challenge_method",
            )
        ]

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    user: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="oauth_grants",
    )

    scoped_teams: ArrayField = ArrayField(models.IntegerField(), null=True, blank=True)
    scoped_organizations: ArrayField = ArrayField(models.CharField(max_length=100), null=True, blank=True)
