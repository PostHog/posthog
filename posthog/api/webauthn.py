import json
import uuid
from typing import Any, cast

from django.contrib.auth import authenticate, login
from django.contrib.auth.signals import user_login_failed
from django.http.response import JsonResponse

import structlog
from axes.exceptions import AxesBackendPermissionDenied
from axes.handlers.proxy import AxesProxyHandler
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.decode_credential_public_key import decode_credential_public_key
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from posthog.api.authentication import axes_locked_out
from posthog.auth import (
    SessionAuthentication,
    WebAuthnAuthenticationResponse,
    WebauthnBackend,
    get_webauthn_rp_id,
    get_webauthn_rp_origin,
)
from posthog.event_usage import report_user_logged_in
from posthog.helpers.two_factor_session import set_two_factor_verified_in_session
from posthog.models import User
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.webauthn_credential import WebauthnCredential

logger = structlog.get_logger(__name__)

# Session keys for webauthn challenges
WEBAUTHN_REGISTRATION_CHALLENGE_KEY = "webauthn_registration_challenge"
WEBAUTHN_REGISTRATION_CREDENTIAL_ID_KEY = "webauthn_registration_credential_id"
WEBAUTHN_VERIFICATION_CHALLENGE_KEY = "webauthn_verification_challenge"
WEBAUTHN_LOGIN_CHALLENGE_KEY = "webauthn_login_challenge"
CHALLENGE_TIMEOUT_MS = 300000  # 5 minutes
SUPPORTED_PUB_KEY_ALGS = [
    COSEAlgorithmIdentifier.ECDSA_SHA_512,
    COSEAlgorithmIdentifier.ECDSA_SHA_256,
    COSEAlgorithmIdentifier.EDDSA,
]


def user_uuid_to_handle(user_uuid: uuid.UUID) -> bytes:
    """Convert a user's UUID to bytes for use as a WebAuthn user handle."""
    return user_uuid.bytes


class WebAuthnRegistrationViewSet(viewsets.ViewSet):
    """
    ViewSet for WebAuthn passkey registration.

    Registration flow:
    1. POST /begin - Generate challenge and options
    2. POST /complete - Verify attestation, store credential (unverified)
    3. POST /verify - Generate verification challenge
    4. POST /verify_complete - Verify assertion, mark credential as verified
    """

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    @action(detail=False, methods=["POST"], url_path="begin")
    def begin(self, request: Request) -> Response:
        """
        Begin passkey registration by generating challenge and options.

        Returns PublicKeyCredentialCreationOptions for the browser.
        """
        user = cast(User, request.user)

        self._raise_if_sso_enforced(user)

        # Get existing credentials to exclude
        existing_credentials = WebauthnCredential.objects.filter(user=user, verified=True)
        exclude_credentials = [
            PublicKeyCredentialDescriptor(
                id=cred.credential_id,
                transports=[AuthenticatorTransport(t) for t in cred.transports if t],
            )
            for cred in existing_credentials
        ]

        # Use user.uuid as the user handle for discoverable credentials
        user_handle = user_uuid_to_handle(user.uuid)

        options = generate_registration_options(
            rp_id=get_webauthn_rp_id(),
            rp_name="PostHog",
            user_id=user_handle,
            user_name=user.email,
            user_display_name=user.get_full_name() or user.email,
            exclude_credentials=exclude_credentials,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            timeout=CHALLENGE_TIMEOUT_MS,
            # manually specifying the allowed algorithms to avoid algorithms that may be insecure or have too small key sizes
            supported_pub_key_algs=SUPPORTED_PUB_KEY_ALGS,
        )

        # Store challenge in session
        request.session[WEBAUTHN_REGISTRATION_CHALLENGE_KEY] = bytes_to_base64url(options.challenge)
        request.session.save()

        logger.info("webauthn_registration_begin", user_id=user.pk, rp_id=get_webauthn_rp_id())

        return Response(json.loads(options_to_json(options)))

    @action(detail=False, methods=["POST"], url_path="complete")
    def complete(self, request: Request) -> Response:
        """
        Complete passkey registration by verifying attestation and storing credential.

        The credential is stored but marked as unverified until the user proves they can use it.
        """
        user = cast(User, request.user)

        self._raise_if_sso_enforced(user)

        # Get challenge from session
        challenge_b64 = request.session.pop(WEBAUTHN_REGISTRATION_CHALLENGE_KEY, None)
        request.session.save()

        if not challenge_b64:
            return Response(
                {"error": "No registration challenge found. Please start registration again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            expected_challenge = base64url_to_bytes(challenge_b64)

            # Parse the credential from request
            credential_data = request.data

            verification = verify_registration_response(
                credential=credential_data,
                expected_challenge=expected_challenge,
                expected_rp_id=get_webauthn_rp_id(),
                expected_origin=get_webauthn_rp_origin(),
                require_user_verification=True,  # refers to authenticator behavior, NOT whether posthog has verified the credential
                supported_pub_key_algs=SUPPORTED_PUB_KEY_ALGS,
            )

            # Parse transports from the response
            transports = credential_data.get("response", {}).get("transports", [])

            # Decode the public key to get the algorithm
            decoded_public_key = decode_credential_public_key(verification.credential_public_key)

            # Create the credential (unverified)
            credential = WebauthnCredential.objects.create(
                user=user,
                credential_id=verification.credential_id,
                label=request.data.get("label", "Passkey"),
                public_key=verification.credential_public_key,
                algorithm=decoded_public_key.alg,
                counter=verification.sign_count,
                transports=transports,
                verified=False,
            )

            # Store credential ID for verification step
            request.session[WEBAUTHN_REGISTRATION_CREDENTIAL_ID_KEY] = str(credential.pk)
            request.session.save()

            logger.info("webauthn_registration_complete", user_id=user.pk, credential_id=credential.pk)

            return Response(
                {
                    "success": True,
                    "credential_id": str(credential.pk),
                    "message": "Credential stored. Please verify your passkey to complete registration.",
                }
            )

        except Exception as e:
            logger.exception("webauthn_registration_error", user_id=user.pk, error=str(e))
            return Response(
                {"error": f"Registration failed: could not complete registration"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _raise_if_sso_enforced(self, user: User) -> None:
        organization = user.current_organization
        if not organization:
            return

        sso_enforcement = OrganizationDomain.objects.get_sso_enforcement_for_email_address(
            user.email, organization=organization
        )
        if not sso_enforcement:
            return

        raise serializers.ValidationError(
            "Passkeys can't be added because your organization requires SSO.",
            code="sso_enforced",
        )


class WebAuthnLoginViewSet(viewsets.ViewSet):
    """
    ViewSet for WebAuthn passkey login (authentication).

    Login flow:
    1. POST /begin - Generate challenge with no allowCredentials (discoverable)
    2. POST /complete - Verify assertion, lookup user by userHandle, login
    """

    permission_classes = [permissions.AllowAny]

    @action(detail=False, methods=["POST"], url_path="begin")
    def begin(self, request: Request) -> Response:
        """
        Begin passkey login by generating an authentication challenge.

        Uses discoverable credentials (empty allowCredentials) so the authenticator
        presents all available passkeys for this RP.
        """
        options = generate_authentication_options(
            rp_id=get_webauthn_rp_id(),
            allow_credentials=[],  # Empty for discoverable credentials
            user_verification=UserVerificationRequirement.REQUIRED,
            timeout=CHALLENGE_TIMEOUT_MS,
        )

        # Store challenge in session
        request.session[WEBAUTHN_LOGIN_CHALLENGE_KEY] = bytes_to_base64url(options.challenge)
        request.session.save()

        logger.info("webauthn_login_begin", rp_id=get_webauthn_rp_id())

        return Response(json.loads(options_to_json(options)))

    @action(detail=False, methods=["POST"], url_path="complete")
    def complete(self, request: Request) -> Response | JsonResponse:
        """
        Complete passkey login by verifying the assertion.

        Uses WebauthnBackend to verify the credential and authenticate the user.
        """
        challenge = request.session.pop(WEBAUTHN_LOGIN_CHALLENGE_KEY, None)
        request.session.save()

        if not challenge:
            return Response(
                {"error": "No login challenge found. Please start login again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request data format
        response_data: dict[str, Any] = request.data.get("response", {})
        user_handle_b64 = response_data.get("userHandle")

        if not user_handle_b64:
            return Response(
                {"error": "No userHandle in response. Make sure you're using a discoverable credential."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        credential_id = request.data.get("rawId")
        if not credential_id:
            return Response(
                {"error": "No credential ID in response."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate response structure
        if not all(key in response_data for key in ("authenticatorData", "clientDataJSON", "signature")):
            return Response(
                {"error": "Invalid response structure. Missing required fields."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Type the response data
        typed_response: WebAuthnAuthenticationResponse = {
            "authenticatorData": response_data["authenticatorData"],
            "clientDataJSON": response_data["clientDataJSON"],
            "signature": response_data["signature"],
            "userHandle": user_handle_b64,
        }

        # Track if user was already authenticated (for re-auth detection)
        was_authenticated_before_login_attempt = request.user is not None and request.user.is_authenticated

        # Extract user early for axes lockout checking
        user = self._extract_user_from_user_handle(user_handle_b64)

        # If we can't extract user from userHandle, return generic error
        if not user:
            return Response(
                {"error": "Authentication failed. Please check your passkey and try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check axes lockout before attempting authentication
        if lockout_response := self._check_axes_lockout(request, user):
            return lockout_response

        # Check SSO enforcement before attempting authentication
        if sso_enforcement_response := self._check_sso_enforcement(user):
            return sso_enforcement_response

        try:
            authenticated_user = authenticate(
                request=request,
                credential_id=credential_id,
                challenge=challenge,
                response=typed_response,
                backend=WebauthnBackend,  # no reason to use password or social auth backends
            )

            if not authenticated_user:
                # Authentication failed - record failure with axes
                if lockout_response := self._handle_authentication_failure(request, user):
                    return lockout_response

                return Response(
                    {"error": "Authentication failed. Please check your passkey and try again."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Login the user with the WebauthnBackend
            login(request, authenticated_user, backend="posthog.auth.WebauthnBackend")

            # Passkey bypasses 2FA
            set_two_factor_verified_in_session(request)

            request.session["reauth"] = "true" if was_authenticated_before_login_attempt else "false"
            request.session.save()

            report_user_logged_in(cast(User, authenticated_user), social_provider="passkey")

            return Response({"success": True})

        except AxesBackendPermissionDenied:
            return axes_locked_out(request)
        except Exception as e:
            logger.exception("webauthn_login_error", error=str(e))
            return Response(
                {"error": f"Login failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _extract_user_from_user_handle(self, user_handle_b64: str) -> User | None:
        """Extract user from base64url-encoded userHandle (UUID bytes)."""
        try:
            user_handle_bytes = base64url_to_bytes(user_handle_b64)
            user_uuid = uuid.UUID(bytes=user_handle_bytes)
            return User.objects.filter(uuid=user_uuid).first()
        except Exception:
            return None

    def _check_sso_enforcement(self, user: User) -> Response | None:
        """Check SSO enforcement for the user. Returns SSO error response if enforced, None otherwise."""
        sso_enforcement = OrganizationDomain.objects.get_sso_enforcement_for_email_address(user.email)
        if sso_enforcement:
            return Response(
                {"error": "You can only login with SSO for this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

    def _check_axes_lockout(self, request: Request, user: User) -> JsonResponse | None:
        """Check if axes has locked out this user/IP. Returns lockout response if locked, None otherwise."""
        axes_request = getattr(request, "_request", request)
        axes_credentials = {"username": user.email}

        if AxesProxyHandler.is_locked(axes_request, credentials=axes_credentials):
            return axes_locked_out(request)
        return None

    def _handle_authentication_failure(self, request: Request, user: User | None) -> JsonResponse | None:
        """Record authentication failure with axes. Returns lockout response if triggered, None otherwise."""
        if not user:
            return None

        axes_request = getattr(request, "_request", request)
        axes_credentials = {"username": user.email}

        try:
            user_login_failed.send(
                sender=WebauthnBackend,
                credentials=axes_credentials,
                request=axes_request,
            )
            # Check if this failure triggered a lockout
            if AxesProxyHandler.is_locked(axes_request, credentials=axes_credentials):
                return axes_locked_out(request)
        except Exception:
            # If axes recording fails, log but continue with generic error
            logger.warning("webauthn_axes_recording_failed", exc_info=True)

        return None


def get_authenticator_type(transports: list[str]) -> str:
    """Determine authenticator type from transports."""
    if not transports:
        return "unknown"

    # Platform authenticators (software-based, like Touch ID, Windows Hello)
    if "internal" in transports and "hybrid" not in transports:
        return "platform"

    # Cross-device authenticators (hybrid)
    if "hybrid" in transports:
        return "hybrid"

    # External authenticators (hardware keys like YubiKey)
    if "usb" in transports or "nfc" in transports or "ble" in transports:
        return "hardware"

    return "unknown"


class WebAuthnCredentialSerializer(serializers.ModelSerializer):
    """Serializer for listing WebAuthn credentials."""

    authenticator_type = serializers.SerializerMethodField()

    class Meta:
        model = WebauthnCredential
        fields = ["id", "label", "created_at", "transports", "verified", "authenticator_type"]
        read_only_fields = ["id", "created_at", "transports", "verified", "authenticator_type"]

    def get_authenticator_type(self, obj: WebauthnCredential) -> str:
        """Compute authenticator type from transports."""
        return get_authenticator_type(obj.transports)


class WebAuthnCredentialViewSet(viewsets.ViewSet):
    """
    ViewSet for managing WebAuthn credentials.

    Allows users to list, rename, and delete their passkeys.
    """

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [SessionAuthentication]

    def list(self, request: Request) -> Response:
        """List all passkeys for the current user (verified and unverified)."""
        user = cast(User, request.user)
        credentials = WebauthnCredential.objects.filter(user=user).order_by("-created_at")
        serializer = WebAuthnCredentialSerializer(credentials, many=True)
        return Response(serializer.data)

    def destroy(self, request: Request, pk: Any = None) -> Response:
        """Delete a passkey."""
        user = cast(User, request.user)

        try:
            credential = WebauthnCredential.objects.get(pk=pk, user=user)
            credential.delete()
            logger.info("webauthn_credential_deleted", user_id=user.pk, credential_id=pk)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except WebauthnCredential.DoesNotExist:
            return Response(
                {"error": "Credential not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

    def partial_update(self, request: Request, pk: Any = None) -> Response:
        """Rename a passkey."""
        user = cast(User, request.user)

        try:
            credential = WebauthnCredential.objects.get(pk=pk, user=user)
        except WebauthnCredential.DoesNotExist:
            return Response(
                {"error": "Credential not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        label = request.data.get("label")
        if not label or len(label) > 200:
            return Response(
                {"error": "Label is required and must be 200 characters or less."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        credential.label = label
        credential.save()

        logger.info("webauthn_credential_renamed", user_id=user.pk, credential_id=pk)

        serializer = WebAuthnCredentialSerializer(credential)
        return Response(serializer.data)

    @action(detail=True, methods=["POST"], url_path="verify")
    def verify(self, request: Request, pk: Any = None) -> Response:
        """Begin verification of an existing passkey."""
        user = cast(User, request.user)

        try:
            credential = WebauthnCredential.objects.get(pk=pk, user=user)
        except WebauthnCredential.DoesNotExist:
            return Response(
                {"error": "Credential not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if credential.verified:
            return Response(
                {"error": "Credential is already verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Generate authentication options for this specific credential
        options = generate_authentication_options(
            rp_id=get_webauthn_rp_id(),
            allow_credentials=[
                PublicKeyCredentialDescriptor(
                    id=credential.credential_id,
                    transports=[AuthenticatorTransport(t) for t in credential.transports if t],
                )
            ],
            user_verification=UserVerificationRequirement.REQUIRED,
            timeout=CHALLENGE_TIMEOUT_MS,
        )

        # Store challenge and credential ID in session
        request.session[WEBAUTHN_VERIFICATION_CHALLENGE_KEY] = bytes_to_base64url(options.challenge)
        request.session[WEBAUTHN_REGISTRATION_CREDENTIAL_ID_KEY] = str(credential.pk)
        request.session.save()

        logger.info("webauthn_credential_verify_begin", user_id=user.pk, credential_id=credential.pk)

        return Response(json.loads(options_to_json(options)))

    @action(detail=True, methods=["POST"], url_path="verify_complete")
    def verify_complete(self, request: Request, pk: Any = None) -> Response:
        """Complete verification of an existing passkey."""
        user = cast(User, request.user)

        challenge_b64 = request.session.pop(WEBAUTHN_VERIFICATION_CHALLENGE_KEY, None)
        session_credential_id = request.session.pop(WEBAUTHN_REGISTRATION_CREDENTIAL_ID_KEY, None)
        request.session.save()

        if not challenge_b64 or not session_credential_id:
            return Response(
                {"error": "No pending verification. Please start verification again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            pk_str = str(pk)
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid credential ID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if session_credential_id != pk_str:
            return Response(
                {"error": "Credential ID mismatch."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            credential = WebauthnCredential.objects.get(pk=pk, user=user, verified=False)
        except WebauthnCredential.DoesNotExist:
            return Response(
                {"error": "Credential not found or already verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            expected_challenge = base64url_to_bytes(challenge_b64)

            verification = verify_authentication_response(
                credential=request.data,
                expected_challenge=expected_challenge,
                expected_rp_id=get_webauthn_rp_id(),
                expected_origin=get_webauthn_rp_origin(),
                credential_public_key=credential.public_key,
                credential_current_sign_count=credential.counter,
                require_user_verification=True,
            )

            # Mark credential as verified
            credential.verified = True
            credential.counter = verification.new_sign_count
            credential.save()

            logger.info("webauthn_credential_verify_complete", user_id=user.pk, credential_id=credential.pk)

            serializer = WebAuthnCredentialSerializer(credential)
            return Response(serializer.data)

        except Exception as e:
            logger.exception("webauthn_credential_verify_error", user_id=user.pk, error=str(e))
            return Response(
                {"error": f"Verification failed: could not complete verification"},
                status=status.HTTP_400_BAD_REQUEST,
            )
