from rest_framework import serializers

from ..facade.enums import DevTokenClient, DevTokenStatus

PKCE_CHALLENGE_PATTERN = r"^[A-Za-z0-9_-]{43}$"
PKCE_VERIFIER_PATTERN = r"^[A-Za-z0-9._~-]{43,128}$"


class DevTokenSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Token id, used to revoke it.")
    client = serializers.ChoiceField(choices=DevTokenClient.choices, help_text="Where the token was minted.")
    cap_usd = serializers.DecimalField(max_digits=10, decimal_places=2, help_text="Most the token can spend, in USD.")
    created_at = serializers.DateTimeField(help_text="When the token was minted.")
    expires_at = serializers.DateTimeField(allow_null=True, help_text="When the gateway stops accepting the token.")
    revoked_at = serializers.DateTimeField(allow_null=True, help_text="When the token was revoked, if it was.")
    status = serializers.ChoiceField(
        choices=DevTokenStatus.choices, help_text="Whether the token still works: live, revoked or expired."
    )


class DevTokenUsageSerializer(serializers.Serializer):
    daily_cap_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Most token caps one user can mint in 24 hours, in USD."
    )
    used_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Token caps the user minted in the last 24 hours, in USD."
    )
    token_cap_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, help_text="Cap of each new token, in USD."
    )
    ttl_seconds = serializers.IntegerField(help_text="Lifetime of each new token, in seconds.")
    tokens = DevTokenSerializer(
        many=True,
        help_text="Tokens the user minted in the last 24 hours, newest first, including revoked and expired ones.",
    )


class MintedDevTokenSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Token id, used to revoke it.")
    token = serializers.CharField(help_text="The phe_ bearer. Shown once; only its hash is stored.")
    cap_usd = serializers.DecimalField(max_digits=10, decimal_places=2, help_text="Most the token can spend, in USD.")
    expires_at = serializers.DateTimeField(help_text="When the gateway stops accepting the token.")
    gateway_url = serializers.CharField(help_text="Base URL of the AI gateway the token is valid on.")
    product = serializers.CharField(help_text="Product the token's spend is attributed to.")


class DevTokenRevokeSerializer(serializers.Serializer):
    id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Token to revoke. Omit to revoke all of the user's live tokens."
    )


class DevTokenRevokedSerializer(serializers.Serializer):
    revoked_count = serializers.IntegerField(help_text="How many tokens the gateway revoked.")


class CliAuthorizeSerializer(serializers.Serializer):
    code_challenge = serializers.RegexField(
        PKCE_CHALLENGE_PATTERN, help_text="base64url SHA-256 of the CLI's PKCE code_verifier, without padding."
    )


class CliAuthorizedSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="One-time code for the CLI to exchange within two minutes.")


class CliExchangeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=128, help_text="Code from the authorize step.")
    code_verifier = serializers.RegexField(
        PKCE_VERIFIER_PATTERN, help_text="PKCE code_verifier whose S256 challenge was authorized."
    )


class DevTokenRefusalSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable refusal code, for example daily_limit or not_staff.")
    detail = serializers.CharField(help_text="Human-readable reason.")
