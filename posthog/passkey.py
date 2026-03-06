"""
Secure wrapper functions for passkey operations.

This module provides a secure interface to the webauthn library, enforcing
security best practices and consistent configuration across all passkey operations.
If you need webauthn without strict user verification/biometrics, use the
webauthn library directly (or create a new webauthn.py helper).
"""

from urllib.parse import urlparse

from django.conf import settings

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.authentication.verify_authentication_response import VerifiedAuthentication
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialCreationOptions,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRequestOptions,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from webauthn.registration.verify_registration_response import VerifiedRegistration

# Challenge timeout in milliseconds (1 minute)
CHALLENGE_TIMEOUT_MS = 60000

# Secure public key algorithms - rejects weak algorithms like RSA with small key sizes
SUPPORTED_PUB_KEY_ALGS = [
    COSEAlgorithmIdentifier.ECDSA_SHA_512,
    COSEAlgorithmIdentifier.ECDSA_SHA_256,
    COSEAlgorithmIdentifier.EDDSA,
]


def get_webauthn_rp_id() -> str:
    """Get the Relying Party ID from SITE_URL."""
    parsed = urlparse(settings.SITE_URL)
    return parsed.hostname or "localhost"


def get_webauthn_rp_origin() -> str:
    """Get the Relying Party origin from SITE_URL."""
    parsed = urlparse(settings.SITE_URL)
    if parsed.port and parsed.port not in (80, 443):
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname}"


def generate_passkey_registration_options(
    user_id: bytes,
    user_name: str,
    user_display_name: str,
    exclude_credentials: list[PublicKeyCredentialDescriptor] | None = None,
) -> PublicKeyCredentialCreationOptions:
    """
    Generate secure WebAuthn registration options.

    Args:
        user_id: User identifier as bytes (typically user.uuid.bytes)
        user_name: User's account identifier (typically email)
        user_display_name: User's display name
        exclude_credentials: List of existing credentials to exclude

    Returns:
        PublicKeyCredentialCreationOptions for the browser
    """
    return generate_registration_options(
        user_id=user_id,
        user_name=user_name,
        user_display_name=user_display_name,
        exclude_credentials=exclude_credentials or [],
        # static values
        rp_id=get_webauthn_rp_id(),
        rp_name="PostHog",
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        timeout=CHALLENGE_TIMEOUT_MS,
        supported_pub_key_algs=SUPPORTED_PUB_KEY_ALGS,
    )


def verify_passkey_registration_response(
    credential: dict,
    expected_challenge: bytes,
) -> VerifiedRegistration:
    """
    Verify a WebAuthn registration response with secure defaults.

    Args:
        credential: The credential response from the browser
        expected_challenge: The challenge bytes that were sent to the browser

    Returns:
        VerifiedRegistration with verified credential data
    """
    return verify_registration_response(
        credential=credential,
        expected_challenge=expected_challenge,
        # static values
        expected_rp_id=get_webauthn_rp_id(),
        expected_origin=get_webauthn_rp_origin(),
        require_user_verification=True,
        supported_pub_key_algs=SUPPORTED_PUB_KEY_ALGS,
    )


def generate_passkey_authentication_options(
    allow_credentials: list[PublicKeyCredentialDescriptor] | None = None,
) -> PublicKeyCredentialRequestOptions:
    """
    Generate secure WebAuthn authentication options.

    Args:
        allow_credentials: List of credentials to allow (empty for discoverable credentials)

    Returns:
        PublicKeyCredentialRequestOptions for the browser
    """
    return generate_authentication_options(
        allow_credentials=allow_credentials or [],
        # static values
        rp_id=get_webauthn_rp_id(),
        user_verification=UserVerificationRequirement.REQUIRED,
        timeout=CHALLENGE_TIMEOUT_MS,
    )


def verify_passkey_authentication_response(
    credential: dict,
    expected_challenge: bytes,
    credential_public_key: bytes,
    credential_current_sign_count: int,
) -> VerifiedAuthentication:
    """
    Verify a WebAuthn authentication response with secure defaults.

    Args:
        credential: The credential response from the browser
        expected_challenge: The challenge bytes that were sent to the browser
        credential_public_key: The stored public key for this credential
        credential_current_sign_count: The stored sign count for replay detection

    Returns:
        VerifiedAuthentication with verification result
    """
    return verify_authentication_response(
        credential=credential,
        expected_challenge=expected_challenge,
        credential_public_key=credential_public_key,
        credential_current_sign_count=credential_current_sign_count,
        # static values
        expected_rp_id=get_webauthn_rp_id(),
        expected_origin=get_webauthn_rp_origin(),
        require_user_verification=True,
    )
