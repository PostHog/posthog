import re
import json
import math
import time
import random
import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any, TypedDict, cast
from urllib.parse import urlencode, urljoin
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import (
    authenticate,
    login,
    logout as auth_logout,
)
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.signals import user_login_failed
from django.contrib.auth.tokens import PasswordResetTokenGenerator as DefaultPasswordResetTokenGenerator
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

import structlog
from axes.exceptions import AxesBackendPermissionDenied
from axes.handlers.proxy import AxesProxyHandler
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from requests import RequestException
from rest_framework import exceptions, mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from social_core.actions import do_complete
from social_core.backends.base import BaseAuth
from social_core.backends.github import GithubOAuth2
from social_core.exceptions import AuthConnectionError, AuthFailed, AuthMissingParameter, AuthStateForbidden
from social_django.models import UserSocialAuth
from social_django.strategy import DjangoStrategy
from social_django.utils import load_backend, load_strategy
from social_django.views import _do_login, auth
from two_factor.utils import default_device
from two_factor.views.core import REMEMBER_COOKIE_PREFIX
from two_factor.views.utils import get_remember_device_cookie, validate_remember_device_cookie
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json
from webauthn.helpers.structs import AuthenticatorTransport, PublicKeyCredentialDescriptor

from posthog.api.email_verification import email_verification_code_verifier, is_email_verification_disabled
from posthog.auth import ACCOUNT_BLOCKED_DETAIL
from posthog.caching.login_device_cache import check_and_cache_login_device
from posthog.constants import AUTH_BACKEND_DISPLAY_NAMES, POSTHOG_INTERNAL_EMAIL_SUFFIX
from posthog.dataclasses import frozen
from posthog.email import EmailRecipientUndeliverableError, is_email_available
from posthog.event_usage import report_user_logged_in, report_user_password_reset
from posthog.exceptions_capture import capture_exception
from posthog.geoip import get_geoip_properties
from posthog.helpers.dev_login import is_dev_login_allowed
from posthog.helpers.dev_oauth_connectors import seeded_dev_oauth_connector_links
from posthog.helpers.email_utils import EmailLookupHandler
from posthog.helpers.impersonation import end_impersonation
from posthog.helpers.sso import (
    GITHUB_EMAIL_LOOKUP_ERROR,
    IDP_SSO_BACKENDS,
    UNVERIFIED_SOCIAL_EMAIL_ERROR,
    get_safe_next_url,
    idp_authentication_is_fresh,
    idp_identity_key,
    is_sso_reauth_begin,
    saml_identity_issuer,
    sso_failure_redirect_url,
)
from posthog.helpers.two_factor_session import (
    CODE_BASED_VERIFICATION_SSO_SESSION_KEY,
    CODE_MAX_ATTEMPTS,
    LOGIN_CODE_VERIFICATION_COUNTER,
    clear_two_factor_session_flags,
    code_based_verifier,
    has_passkeys,
    is_backup_code_attempt,
    normalize_verification_code,
    set_two_factor_verified_in_session,
)
from posthog.helpers.user_devices import has_valid_known_device_cookie
from posthog.helpers.verified_domain_enforcement import VERIFIED_DOMAIN_REQUIRED_ERROR, resolve_login_organization
from posthog.inbox_providers import InboxProvider, InboxProviderLookup
from posthog.models import IdentityProviderConfig, OrganizationDomain, User
from posthog.models.activity_logging import signal_handlers  # imported for its signal receivers too
from posthog.models.identity_provider_email_verification import IdentityProviderEmailVerification
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.passkey import generate_passkey_authentication_options, verify_passkey_authentication_response
from posthog.rate_limit import (
    CodeBasedVerificationResendThrottle,
    CodeBasedVerificationThrottle,
    LoginPrecheckThrottle,
    SSOLoginThrottle,
    TwoFactorBackupCodeThrottle,
    TwoFactorThrottle,
    UserPasswordResetThrottle,
)
from posthog.session.activity import revoke_other_sessions
from posthog.tasks.email import (
    login_from_new_device_notification,
    send_password_reset,
    send_two_factor_auth_backup_code_used_email,
)
from posthog.utils import (
    get_instance_available_sso_providers,
    get_ip_address,
    get_short_user_agent,
    get_trusted_client_ip,
)
from posthog.workos_radar import (
    RadarAction,
    RadarAuthMethod,
    SuspiciousAttemptBlocked,
    evaluate_auth_attempt,
    radar_client_id_for_login,
)
from posthog.workos_radar_signal_handlers import extend_login_attempt, remember_login_attempt

from products.security.backend.facade.api import (
    REFUSAL_CODE as SECURITY_REFUSAL_CODE,
    access_refused as security_access_refused,
)
from products.security.backend.facade.contracts import SubjectInput as SecuritySubject
from products.security.backend.facade.enums import Surface as SecuritySurface

if TYPE_CHECKING:
    from posthog.api.oidc import MultitenantOIDCAuth
    from posthog.api.sso import MultitenantSAMLAuth

logger = structlog.get_logger("posthog.auth")
mfa_logger = structlog.get_logger("posthog.auth.mfa")


class WebauthnCredentialPrecheck(TypedDict):
    id: str
    type: str
    transports: list[str]


class PendingIdPEmailVerification(TypedDict):
    provider: str
    issuer: str
    subject: str
    uid: str
    email: str
    target_email: str
    authenticated_at: int
    user_id: int
    issued_at: int
    partial_token: str


def sso_enforcement_for_login_address(email: str, user: User | None) -> str | None:
    """
    Return the SSO enforcement for a typed address or for the account it resolves to.

    The account lookup folds case in Postgres, so a typed domain can differ from the domain on the account it
    reaches: Postgres lowercases `İ` (U+0130) to `i`. Checking only the typed domain would let an address that
    reaches an account on an enforced domain skip SSO, so the account's own address is checked too.
    """
    sso_enforcement = OrganizationDomain.objects.get_sso_enforcement_for_email_address(email)
    if sso_enforcement or user is None:
        return sso_enforcement
    return OrganizationDomain.objects.get_sso_enforcement_for_email_address(user.email)


# Reasons a logout can pass to the login page, which holds the copy for each one.
_LOGOUT_REASONS = frozenset({SECURITY_REFUSAL_CODE})


@require_http_methods(["POST"])
def logout(request):
    clear_two_factor_session_flags(request)

    request.session.pop("reauth", None)

    if is_impersonated_session(request):
        impersonated_user_pk = request.user.pk
        end_impersonation(request)
        return redirect(f"/admin/posthog/user/{impersonated_user_pk}/change/")

    auth_logout(request)

    reason = request.POST.get("reason", "")
    if reason in _LOGOUT_REASONS:
        return redirect(f"{settings.LOGIN_URL}?{urlencode({'error_code': reason})}")

    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect_to_login(next_url, login_url=settings.LOGIN_URL)

    return redirect(settings.LOGIN_URL)


def axes_locked_out(*args, **kwargs):
    return JsonResponse(
        {
            "type": "authentication_error",
            "code": "too_many_failed_attempts",
            "detail": "Too many failed login attempts. Please try again in"
            f" {int(settings.AXES_COOLOFF_TIME.seconds / 60)} minutes.",
            "attr": None,
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def sso_login(request: HttpRequest, backend: str) -> HttpResponse:
    sso_login_throttle = SSOLoginThrottle()
    if not sso_login_throttle.allow_request(cast(Request, request), view=cast(APIView, None)):
        response = HttpResponse("Too many requests. Please try again later.", status=429)
        wait = sso_login_throttle.wait()
        if wait is not None:
            response["Retry-After"] = str(math.ceil(wait))
        return response

    sso_providers = get_instance_available_sso_providers()
    # because SAML is configured at the domain-level, we have to assume it's enabled for someone in the instance
    sso_providers["saml"] = settings.EE_AVAILABLE
    sso_providers["oidc"] = settings.EE_AVAILABLE

    is_reauth = is_sso_reauth_begin(request)

    # Checked before any session mutation below, so a misconfigured provider can never sign anyone out.
    if backend not in sso_providers:
        return redirect(sso_failure_redirect_url(request, "invalid_sso_provider", is_reauth=is_reauth))

    if not sso_providers[backend]:
        return redirect(sso_failure_redirect_url(request, "improperly_configured_sso", is_reauth=is_reauth))

    # The one known `connect_from` value is "posthog_code" - what PH Code uses when linking GH profile to PostHog user
    connect_from = (request.GET.get("connect_from") or "").strip()
    if connect_from and backend == "github":
        if not request.user.is_authenticated:
            request.session.flush()
        # For linking GitHub, keep the session and set the next URL to /account-connected/github-login
        # (see frontend AccountConnected). QueryDict must be copied before mutation (GET is often immutable).
        query_dict = request.GET.copy()
        query_dict["next"] = (
            f"/account-connected/github-login?{urlencode({'provider': backend, 'connect_from': connect_from})}"
        )
        request.GET = query_dict  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
    elif not is_reauth:
        # This is the default case - for regular login, we flush the session (log out)
        request.session.flush()
    # Re-auth keeps the session: the user is already signed in, and flushing here would sign them out
    # before the IdP is even contacted, so any hiccup in the round trip would strand them at /login.
    # `social_reauth_complete` grants the step-up on the way back in.

    try:
        response = auth(request, backend)
        if backend == "saml" and (nonce := request.session.pop("saml_browser_nonce", None)):
            from posthog.api.sso import SAML_BROWSER_COOKIE, SAML_RELAY_STATE_CACHE_TTL_SECONDS

            response.set_cookie(
                SAML_BROWSER_COOKIE,
                nonce,
                max_age=SAML_RELAY_STATE_CACHE_TTL_SECONDS,
                secure=True,
                httponly=True,
                samesite="None",
            )
        return response
    except (AuthFailed, AuthMissingParameter, AuthConnectionError) as e:
        # AuthConnectionError covers an unreachable IdP or a TLS cert that fails during OIDC discovery -
        # it's a sibling of AuthFailed (not a subclass), so it would otherwise surface as an unhandled 500.
        logger.warning("SSO login failed, redirecting to login page", exc_info=e)
        return redirect(sso_failure_redirect_url(request, "improperly_configured_sso", is_reauth=is_reauth))


SSO_REAUTH_CHANNEL = "posthog-sso-reauth"


@require_http_methods(["GET"])
def sso_reauth_complete(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "sso_reauth_complete.html",
        {
            "result": {
                "channel": SSO_REAUTH_CHANNEL,
                "attempt": request.GET.get("attempt") or None,
                "error_code": request.GET.get("error_code") or None,
            }
        },
    )


class TwoFactorRequired(APIException):
    status_code = 401
    default_detail = "2FA is required."
    default_code = "2fa_required"


class CodeBasedVerificationRequired(APIException):
    status_code = 401
    default_detail = "Code-based verification is required."
    default_code = "code_based_verification_required"

    def __init__(self, email: str | None = None, inbox_provider: InboxProvider | None = None):
        detail = email if email else self.default_detail
        super().__init__(detail=detail, code=self.default_code)
        self.extra = {"inbox_provider": inbox_provider}


class LoginCodeEmailUndeliverable(APIException):
    status_code = 400
    default_detail = "We can't send email to this address, so we can't send you a login code."
    default_code = "login_code_email_undeliverable"


def _clear_unverified_local_credentials(user: User) -> bool:
    # Deferred because posthog.api.signup imports posthog.api.webauthn, which imports this module.
    from posthog.api.signup import clear_unverified_local_credentials

    return clear_unverified_local_credentials(user)


def _send_login_code(
    request: HttpRequest,
    user: User,
    *,
    is_resend: bool = False,
    target_email: str | None = None,
    identity: str | None = None,
    asserted_email: str | None = None,
) -> bool:
    if target_email is not None:
        from posthog.token_bucket import BucketDecision, Budget, consume

        if not identity:
            return False
        if (
            not is_resend
            and asserted_email is not None
            and code_based_verifier.reuse_recent_idp_code(request, user, target_email, identity, asserted_email)
        ):
            return True
        decision = consume(f"idp_login_code_identity:{identity}", Budget(burst=1, per_hour=60))
        if not isinstance(decision, BucketDecision):
            logger.warning("idp_login_code_rate_limit_unavailable", user_id=user.pk)
            return False
        if not decision.allowed:
            return False
        if not code_based_verifier.reserve_idp_challenge(user, identity):
            return False
        recipient = sha256(target_email.strip().lower().encode()).hexdigest()
        account = consume(f"idp_login_code_account:{user.pk}:{recipient}:{identity}", Budget(burst=2, per_hour=12))
        if not isinstance(account, BucketDecision):
            logger.warning("idp_login_code_account_budget_unavailable", user_id=user.pk)
            return False
        if not account.allowed:
            return False
    try:
        return code_based_verifier.create_and_send_code_based_verification(
            request,
            user,
            is_resend=is_resend,
            target_email=target_email,
            identity=identity,
            asserted_email=asserted_email,
        )
    except EmailRecipientUndeliverableError:
        raise LoginCodeEmailUndeliverable()


class EmailVerificationPending(APIException):
    """Login blocked because the signup email is unverified and a fresh code was just sent.
    Like CodeBasedVerificationRequired, `detail` carries data (the user uuid) so the frontend
    can route to the code entry page at /verify_email/<uuid>."""

    status_code = 401
    default_detail = "Email verification is required."
    default_code = "verify_email_pending"

    def __init__(self, user_uuid: str, inbox_provider: InboxProvider | None = None):
        super().__init__(detail=user_uuid, code=self.default_code)
        self.extra = {"inbox_provider": inbox_provider}


def require_verified_email_for_login(user: User) -> None:
    """
    Send a verification code when the login policy requires it.

    Raises EmailVerificationPending when login may not continue for this user. Legacy users with
    a null verification state get a code but are still allowed to sign in. The error carries the
    user uuid, so call this only after the caller checked a credential.
    """
    if not is_email_available():
        return

    if user.is_email_verified is True:
        return

    if is_email_verification_disabled(user):
        return

    if user.is_email_verified is None:
        email_verification_code_verifier.send_code(user)
        return

    inbox_lookup = InboxProviderLookup.start(user.email)
    email_verification_code_verifier.send_code(user)
    raise EmailVerificationPending(str(user.uuid), inbox_provider=inbox_lookup.result())


class _BrowserTokenField(serializers.Field):
    """A token the login page may send. A value that is not a string reads as empty, so it never fails a login."""

    def to_internal_value(self, data: Any) -> str:
        return data if isinstance(data, str) else ""

    def to_representation(self, value: Any) -> Any:
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()
    radar_signals_id = _BrowserTokenField(
        required=False,
        default="",
        help_text="Token from the WorkOS Radar browser script. It links the device signals the browser collected to this login.",
    )

    def to_representation(self, instance: Any) -> dict[str, Any]:
        return {"success": True}

    def _check_if_2fa_required(self, user: User) -> bool:
        from posthog.helpers.two_factor_session import has_passkeys

        device = default_device(user)
        user_has_passkeys = has_passkeys(user)
        passkeys_enabled_for_2fa = user_has_passkeys and user.passkeys_enabled_for_2fa

        # If user has neither TOTP nor passkeys enabled for 2FA, check for code-based verification remember cookie
        if not device and not passkeys_enabled_for_2fa:
            for key, value in self.context["request"].COOKIES.items():
                if key.startswith(REMEMBER_COOKIE_PREFIX) and value:
                    try:
                        if validate_remember_device_cookie(value, user=user, otp_device_id="code_based_verification"):
                            return False
                    except BadSignature:
                        pass

        # Has TOTP device - check for TOTP remember cookie
        if device:
            for key, value in self.context["request"].COOKIES.items():
                if key.startswith(REMEMBER_COOKIE_PREFIX) and value:
                    try:
                        if validate_remember_device_cookie(value, user=user, otp_device_id=device.persistent_id):
                            user.otp_device = device  # type: ignore
                            device.throttle_reset()
                            return False
                    except BadSignature:
                        # Workaround for signature mismatches due to Django upgrades.
                        # See https://github.com/PostHog/posthog/issues/19350
                        pass

        # Has passkeys enabled for 2FA but no TOTP - 2FA still required (passkey will be used)
        if passkeys_enabled_for_2fa:
            for key, value in self.context["request"].COOKIES.items():
                if key.startswith(REMEMBER_COOKIE_PREFIX) and value:
                    try:
                        if validate_remember_device_cookie(value, user=user, otp_device_id="passkey_2fa"):
                            return False
                    except BadSignature:
                        pass

        # No device and no passkeys enabled for 2FA - should have been handled above, but fallback to code-based verification
        return True

    def create(self, validated_data: dict[str, str]) -> Any:
        existing_user = EmailLookupHandler.get_user_by_email(validated_data["email"], is_active=None)

        # Check SSO enforcement (which happens at the domain level)
        sso_enforcement = sso_enforcement_for_login_address(validated_data["email"], existing_user)
        if sso_enforcement:
            raise serializers.ValidationError(
                f"You can only login with SSO for this account ({sso_enforcement}).",
                code="sso_enforced",
            )

        request = self.context["request"]

        axes_request = getattr(request, "_request", request)
        was_authenticated_before_login_attempt = bool(
            getattr(request, "user", None)
            and request.user.is_authenticated
            and request.user.email.lower() == validated_data["email"].lower()
        )

        # Initialize axes handler via proxy so request metadata is populated consistently
        handler = AxesProxyHandler
        axes_credentials = {"username": validated_data["email"]}

        # Check if axes has locked out this IP/user before attempting authentication
        if handler.is_locked(axes_request, credentials=axes_credentials):
            raise AxesBackendPermissionDenied("Account locked: too many login attempts.")

        # A re-auth comes from a signed-in session, so Radar has nothing to add to it. The login
        # form cannot show a Turnstile challenge, so only a block verdict refuses the login.
        radar_attempt = None
        if not was_authenticated_before_login_attempt:
            try:
                radar_attempt = evaluate_auth_attempt(
                    request=request._request,
                    # Radar knows the account by its stored address, not the variant spelling the lookup folded
                    email=existing_user.email if existing_user else validated_data["email"],
                    action=RadarAction.SIGNIN,
                    auth_method=RadarAuthMethod.PASSWORD,
                    user_id=str(existing_user.distinct_id) if existing_user else None,
                    challenge_allowed=False,
                    call_site="login",
                    signals_id=str(validated_data.get("radar_signals_id") or ""),
                    account_id=str(existing_user.uuid) if existing_user else None,
                )
            except SuspiciousAttemptBlocked:
                # Counts toward the lockout above, so a repeating caller stops costing Radar calls
                user_login_failed.send(
                    sender=__name__, credentials={"email": validated_data["email"]}, request=axes_request
                )
                raise

        user = cast(
            User | None,
            authenticate(
                request,
                email=validated_data["email"],
                password=validated_data["password"],
            ),
        )

        if not user:
            # Axes tracks failed attempts via authentication signals. If this failure triggered a
            # lockout, surface the lockout response instead of the generic credential error.
            if handler.is_locked(axes_request, credentials=axes_credentials):
                raise AxesBackendPermissionDenied("Account locked: too many login attempts.")

            raise serializers.ValidationError("Invalid email or password.", code="invalid_credentials")

        if radar_attempt and radar_attempt.attempt_id:
            # Reported when the session signs in, so a login that stops at a second factor is never reported
            remember_login_attempt(request, radar_attempt.attempt_id, user.pk, valid_for_seconds=CODE_TTL_SECONDS)

        try:
            refused = security_access_refused(
                SecuritySubject(email=user.email, user_uuid=str(user.uuid), ip=get_trusted_client_ip(axes_request)),
                SecuritySurface.APP,
                call_site="login",
            )
        except Exception:
            logger.exception("security_access_check_site_failed", call_site="login")
            refused = False
        if refused:
            raise exceptions.PermissionDenied(ACCOUNT_BLOCKED_DETAIL, code=SECURITY_REFUSAL_CODE)

        require_verified_email_for_login(user)
        code_based_verifier.clear_pending(request)
        if request.session.pop("partial_pipeline_token", None):
            request.session.pop("invite_id", None)

        # Domain enforcement: refuse blocked members — blocked admins still get a gated session.
        if not resolve_login_organization(user):
            raise serializers.ValidationError(
                VERIFIED_DOMAIN_REQUIRED_ERROR,
                code="verified_domain_required",
            )

        # A re-auth keeps the 2FA flag so that the signed-in session works while the user enters
        # the second factor. Without the flag, enforced 2FA refuses every other request until logout.
        if not was_authenticated_before_login_attempt:
            clear_two_factor_session_flags(request)

        if self._check_if_2fa_required(user):
            request.session["user_authenticated_but_no_2fa"] = user.pk
            request.session["user_authenticated_time"] = time.time()

            # Check if user has TOTP device or passkeys enabled for 2FA
            from posthog.helpers.two_factor_session import has_passkeys

            totp_device = default_device(user)
            user_has_passkeys = has_passkeys(user)
            passkeys_enabled_for_2fa = user_has_passkeys and user.passkeys_enabled_for_2fa

            if totp_device or passkeys_enabled_for_2fa:
                # TOTP or passkey flow
                raise TwoFactorRequired()
            else:
                # Code-based verification - skip if this is a reauth (user already authenticated)
                if not was_authenticated_before_login_attempt:
                    inbox_lookup = InboxProviderLookup.start(user.email)
                    code_based_verification_sent = _send_login_code(request, user)
                    if code_based_verification_sent:
                        # Increment the resend throttle counter so the initial send counts towards the limit
                        resend_throttle = CodeBasedVerificationResendThrottle()
                        resend_throttle.allow_request(request, None)  # type: ignore[arg-type]
                        raise CodeBasedVerificationRequired(user.email, inbox_provider=inbox_lookup.result())
                    else:
                        # if we failed to send the email, we should fall through to allow login without code-based verification
                        pass

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        # Log successful authentication with axes
        handler.user_logged_in(None, user=user, request=axes_request)

        if not self._check_if_2fa_required(user):
            set_two_factor_verified_in_session(request)

        # This is auto-handled for social auth providers, but we need to handle it manually for user/pass logins
        request.session["reauth"] = "true" if was_authenticated_before_login_attempt else "false"
        request.session.save()

        # Trigger login notification (password, no-2FA) and skip re-auth
        if not was_authenticated_before_login_attempt and not has_valid_known_device_cookie(request, user):
            short_user_agent = get_short_user_agent(request)
            ip_address = get_ip_address(request)
            backend_name = request.session.get("_auth_user_backend", "django.contrib.auth.backends.ModelBackend")
            login_from_new_device_notification.delay(
                user.id, timezone.now(), short_user_agent, ip_address, backend_name
            )

        report_user_logged_in(user, social_provider="")
        return user


class LoginPrecheckSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def to_representation(
        self, instance: dict[str, str | bool | list[str] | list[WebauthnCredentialPrecheck]]
    ) -> dict[str, str | bool | list[str] | list[WebauthnCredentialPrecheck]]:
        return instance

    def create(self, validated_data: dict[str, str]) -> Any:
        from webauthn.helpers import bytes_to_base64url

        from posthog.models.webauthn_credential import WebauthnCredential

        email = validated_data.get("email", "")
        # TODO: Refactor methods below to remove duplicate queries
        user = EmailLookupHandler.get_user_by_email(email, is_active=None)

        credentials = WebauthnCredential.objects.get_verified_for_email(email)
        webauthn_credentials = [
            {
                "id": bytes_to_base64url(cred.credential_id),
                "type": "public-key",
                "transports": cred.transports or [],
            }
            for cred in credentials
        ]

        saml_available = IdentityProviderConfig.objects.get_is_saml_available_for_email(email)
        oidc_available = IdentityProviderConfig.objects.get_is_oidc_available_for_email(email)

        response: dict[str, Any] = {
            "sso_enforcement": sso_enforcement_for_login_address(email, user),
            "saml_available": saml_available,
            "oidc_available": oidc_available,
            "webauthn_credentials": webauthn_credentials,
            **self._available_local_methods(email, saml_available=saml_available, oidc_available=oidc_available),
        }
        if radar_client_id := radar_client_id_for_login():
            response["radar_client_id"] = radar_client_id
        return response

    @staticmethod
    def _available_local_methods(email: str, *, saml_available: bool, oidc_available: bool = False) -> dict[str, Any]:
        """
        Report whether an account exists for this email, whether it can log in with a password,
        and which of its linked social identities are actually usable on this instance.

        The auth page asks for the email first and uses `account_exists` to choose between the
        login step and the signup step. Signup already refuses an email that has an account, so
        this tells a caller nothing the signup precheck does not.
        """
        # Same lookup login itself uses (`UserManager.get_by_natural_key`), so precheck can never
        # describe a different account than the one a password would authenticate: case-insensitive,
        # and deterministic (active first, then last logged in) if case variations coexist. A
        # deactivated account counts as existing, because signup cannot reuse its email either.
        user = EmailLookupHandler.get_user_by_email(email, is_active=None)
        if user is None:
            return {"account_exists": False, "password_login_available": True, "social_providers": []}

        # Mirrors `UserSerializer.get_has_password`: `has_usable_password()` is True for an empty
        # password, so the `bool(...)` half of the check is load-bearing.
        password_login_available = bool(user.password) and user.has_usable_password()

        usable_providers = {
            provider for provider, available in get_instance_available_sso_providers().items() if available
        }
        if saml_available:
            # SAML is domain-configured rather than instance-configured, so it isn't covered above.
            usable_providers.add("saml")
        linked_providers = set(user.social_auth.values_list("provider", flat=True))
        if oidc_available:
            usable_providers.add("oidc")

        return {
            "account_exists": True,
            "password_login_available": password_login_available,
            "social_providers": sorted(linked_providers & usable_providers),
        }


class NonCreatingViewSetMixin(mixins.CreateModelMixin):
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Method `create()` is overridden to send a more appropriate HTTP
        status code (as no object is actually created).
        """
        response = super().create(request, *args, **kwargs)
        response.status_code = getattr(self, "SUCCESS_STATUS_CODE", status.HTTP_200_OK)

        if response.status_code == status.HTTP_204_NO_CONTENT:
            response.data = None

        return response


class LoginViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = LoginSerializer
    permission_classes = (permissions.AllowAny,)
    # NOTE: Throttling is handled by the `axes` package

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Override to handle axes lockout exceptions."""
        try:
            return super().create(request, *args, **kwargs)
        except Exception as e:
            # Check if this is an axes lockout exception
            if e.__class__.__name__ == "AxesBackendPermissionDenied":
                return axes_locked_out(request)
            raise


# Known good emails seeded by setup_dev / generate_demo_data so the frontend can
# label them. Anything else is shown without a label.
DEV_LOGIN_KNOWN_EMAIL_LABELS = {
    "test@posthog.com": "Default test user",
}

# Name pools for dev-login fresh account creation, so test accounts are easy to
# tell apart in the login tools list.
DEV_ACCOUNT_FIRST_NAMES = [
    "Ada",
    "Byron",
    "Cleo",
    "Dorian",
    "Edith",
    "Felix",
    "Greta",
    "Hugo",
    "Iris",
    "Jonas",
    "Kira",
    "Linus",
    "Mira",
    "Nico",
    "Opal",
    "Pablo",
    "Quinn",
    "Rosa",
    "Silas",
    "Tessa",
]

DEV_ACCOUNT_ORGANIZATION_NAMES = [
    "Acme Analytics",
    "Bluebird Labs",
    "Cindercone Systems",
    "Driftwood Data",
    "Ember Metrics",
    "Ferrous Works",
    "Glimmer Grove",
    "Halcyon House",
    "Ironwood Insights",
    "Juniper Junction",
    "Kestrel Kollective",
    "Lumen Loft",
    "Marble & Moss",
    "Northlight Co.",
    "Obsidian Oak",
    "Pinnacle Patch",
    "Quartz Quarry",
    "Riverstone Research",
    "Solstice Software",
    "Timberline Tools",
]


class DevLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(
        required=False,
        write_only=True,
        help_text="Email of the active user to log in as. Only honored when dev login is allowed (DEBUG and ALLOW_DEV_LOGIN).",
    )
    create_fresh_account = serializers.BooleanField(
        required=False,
        default=False,
        write_only=True,
        help_text="Create a fresh account/org with random names (password: 12345678) and log in directly, without signup. Only honored when dev login is allowed.",
    )

    def to_representation(self, instance: Any) -> dict[str, Any]:
        return {"success": True}

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        # Gate first, before any field-level validation: when dev login is disabled the
        # endpoint must look nonexistent (404) regardless of the request body, so a
        # missing-email 400 can't leak that the route exists.
        if not is_dev_login_allowed():
            raise Http404()
        if not data.get("create_fresh_account") and not data.get("email"):
            raise serializers.ValidationError(
                {"email": serializers.ErrorDetail("This field is required.", code="required")}
            )
        return data

    def create(self, validated_data: dict[str, Any]) -> Any:
        if not is_dev_login_allowed():
            raise Http404()

        if validated_data.get("create_fresh_account"):
            return self._create_fresh_account()

        request = self.context["request"]
        user = EmailLookupHandler.get_user_by_email(validated_data["email"])
        if user is None:
            raise serializers.ValidationError("User not found", code="user_not_found")

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session["reauth"] = "false"
        request.session.save()
        report_user_logged_in(user, social_provider="")
        return user

    def _create_fresh_account(self) -> Any:
        first_name = random.choice(DEV_ACCOUNT_FIRST_NAMES)
        email = f"{first_name.lower()}-{uuid4().hex[:8]}@posthog.dev"
        organization_name = random.choice(DEV_ACCOUNT_ORGANIZATION_NAMES)

        with transaction.atomic():
            _, _, user = User.objects.bootstrap(
                organization_name=organization_name,
                email=email,
                password="12345678",
                first_name=first_name,
                is_email_verified=True,
            )

        request = self.context["request"]
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session["reauth"] = "false"
        request.session.save()
        report_user_logged_in(user, social_provider="")
        return user


class DevLoginUserSerializer(serializers.Serializer):
    email = serializers.EmailField(read_only=True, help_text="Email to log in as.")
    first_name = serializers.CharField(read_only=True, help_text="First name, shown next to the email.")
    is_staff = serializers.BooleanField(read_only=True, help_text="Whether the user is a staff (instance admin) user.")
    # Shadows Field.label, which the metaclass moves aside into _declared_fields at runtime.
    label = serializers.CharField(  # type: ignore[assignment]
        read_only=True, allow_null=True, help_text="Label for accounts seeded by setup_dev, e.g. the default test user."
    )
    last_login = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When this account was last logged in as, or null if never."
    )


class DevOAuthConnectorSerializer(serializers.Serializer):
    client_id = serializers.CharField(
        read_only=True, help_text="Client ID of the connector application, which is its CIMD document URL."
    )
    client_name = serializers.CharField(read_only=True, help_text="Application name, shown on the auth screens.")
    logo_uri = serializers.CharField(
        read_only=True, allow_null=True, help_text="HTTPS logo from the connector's CIMD document, or null."
    )
    redirect_host = serializers.CharField(
        read_only=True, allow_null=True, help_text="Host of the application's redirect URI."
    )
    authorize_path = serializers.CharField(
        read_only=True,
        help_text="The /oauth/authorize path the connector sends people to, for the login page's next parameter.",
    )


class DevLoginUserListSerializer(serializers.Serializer):
    users = DevLoginUserSerializer(
        many=True, read_only=True, help_text="Every active user, seeded accounts first, then most recently used."
    )
    oauth_connectors = DevOAuthConnectorSerializer(
        many=True,
        read_only=True,
        help_text="Connector applications registered by generate_demo_data, to start a pending OAuth connection.",
    )


class DevLoginViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    """
    Dev-only convenience endpoint. Lists active users and lets the login UI
    one-click sign in as any of them without a password. Returns 404 unless
    both DEBUG and ALLOW_DEV_LOGIN are enabled.
    """

    queryset = User.objects.none()
    serializer_class = DevLoginSerializer
    permission_classes = (permissions.AllowAny,)

    @extend_schema(responses={200: DevLoginUserListSerializer})
    def list(self, request: Request) -> Response:
        if not is_dev_login_allowed():
            raise Http404()

        # Seeded accounts first so the default test user stays on top. After that recency beats
        # alphabetical: on instances with hundreds of test accounts, the handful you actually
        # switch between float up on their own. Email breaks ties to keep the order stable.
        users = list(
            User.objects.filter(is_active=True)
            .annotate(is_seeded=Q(email__in=DEV_LOGIN_KNOWN_EMAIL_LABELS))
            .order_by("-is_seeded", F("last_login").desc(nulls_last=True), "email")
            .values("email", "first_name", "is_staff", "last_login")
        )
        for entry in users:
            entry["label"] = DEV_LOGIN_KNOWN_EMAIL_LABELS.get(entry["email"])

        return Response(
            DevLoginUserListSerializer({"users": users, "oauth_connectors": seeded_dev_oauth_connector_links()}).data
        )


class TwoFactorSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)


def _set_remember_device_cookie(response: HttpResponse, user: User, otp_device_id: str) -> None:
    response.set_cookie(
        REMEMBER_COOKIE_PREFIX + str(uuid4()),
        get_remember_device_cookie(user=user, otp_device_id=otp_device_id),
        max_age=settings.TWO_FACTOR_REMEMBER_COOKIE_AGE,
        domain=getattr(settings, "TWO_FACTOR_REMEMBER_COOKIE_DOMAIN", None),
        path=getattr(settings, "TWO_FACTOR_REMEMBER_COOKIE_PATH", "/"),
        secure=getattr(settings, "TWO_FACTOR_REMEMBER_COOKIE_SECURE", True),
        httponly=getattr(settings, "TWO_FACTOR_REMEMBER_COOKIE_HTTPONLY", True),
        samesite=getattr(settings, "TWO_FACTOR_REMEMBER_COOKIE_SAMESITE", "Strict"),
    )


class TwoFactorViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    serializer_class = TwoFactorSerializer
    queryset = User.objects.none()
    permission_classes = (permissions.AllowAny,)
    throttle_classes = [TwoFactorThrottle, TwoFactorBackupCodeThrottle]

    def _token_is_valid(self, request, user: User, device) -> Response:
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        otp_login(request, device)
        set_two_factor_verified_in_session(request)
        report_user_logged_in(user, social_provider="")
        device.throttle_reset()

        # Clean up pre-2FA session keys to prevent reuse
        request.session.pop("user_authenticated_but_no_2fa", None)
        request.session.pop("user_authenticated_time", None)

        response = Response({"success": True})
        _set_remember_device_cookie(response, user, device.persistent_id)
        return response

    def _handle_passkey_2fa(self, request: Request, user: User, credential_id: str, response_data: dict) -> Response:
        """
        Handle passkey-based 2FA authentication.

        Args:
            request: The HTTP request
            user: The user attempting 2FA
            credential_id: Base64-encoded credential ID from the passkey
            response_data: The WebAuthn authentication response data

        Returns:
            Response with success status

        Raises:
            ValidationError: If passkey verification fails
        """
        from posthog.api.webauthn import WEBAUTHN_2FA_CHALLENGE_KEY

        challenge_b64 = request.session.pop(WEBAUTHN_2FA_CHALLENGE_KEY, None)
        if not challenge_b64:
            raise serializers.ValidationError(
                detail="No 2FA challenge found. Please start 2FA again.", code="2fa_no_challenge"
            )

        try:
            # save the session with the challenge removed
            request.session.save()

            credential_id_bytes = base64url_to_bytes(credential_id)
            credential = WebauthnCredential.objects.filter(
                user=user, credential_id=credential_id_bytes, verified=True
            ).first()

            if not credential:
                raise serializers.ValidationError(detail="Invalid passkey.", code="2fa_invalid_passkey")

            # Construct credential dict for webauthn library
            credential_dict = {
                "id": credential_id,
                "rawId": credential_id,
                "response": response_data,
                "type": "public-key",
            }

            # Verify the authentication response
            expected_challenge = base64url_to_bytes(challenge_b64)
            verification = verify_passkey_authentication_response(
                credential=credential_dict,
                expected_challenge=expected_challenge,
                credential_public_key=credential.public_key,
                credential_current_sign_count=credential.counter,
            )

            # Update sign count
            credential.counter = verification.new_sign_count
            credential.save()

            # Complete 2FA verification
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            set_two_factor_verified_in_session(request)
            report_user_logged_in(user, social_provider="")

            # Clean up pre-2FA session keys to prevent reuse
            request.session.pop("user_authenticated_but_no_2fa", None)
            request.session.pop("user_authenticated_time", None)

            # Set remember device cookie for passkey 2FA
            response = Response({"success": True})
            _set_remember_device_cookie(response, user, "passkey_2fa")
            return response
        except serializers.ValidationError:
            raise
        except Exception as e:
            mfa_logger.exception("webauthn_2fa_error", user_id=user.pk, error=str(e))
            raise serializers.ValidationError(
                detail="Passkey verification failed. Please try again.", code="2fa_passkey_failed"
            )

    @staticmethod
    def _too_many_attempts_message(throttle_info: dict[str, Any] | None, can_use_backup_code: bool) -> str:
        locked_until = (throttle_info or {}).get("locked_until")
        if locked_until is None:
            wait = "in a moment"
        else:
            seconds = max(1, math.ceil((locked_until - timezone.now()).total_seconds()))
            if seconds < 60:
                wait = f"in {seconds} second{'s' if seconds != 1 else ''}"
            else:
                minutes = math.ceil(seconds / 60)
                wait = f"in {minutes} minute{'s' if minutes != 1 else ''}"
        if can_use_backup_code:
            return f"Too many attempts. Try again {wait}, or enter one of your backup codes."
        return f"Too many attempts. Try again {wait}."

    def _handle_totp_2fa(self, request: Request, user: User, token: str) -> Response:
        """
        Handle TOTP token or backup code 2FA authentication.

        Args:
            request: The HTTP request
            user: The user attempting 2FA
            token: The TOTP token or backup code

        Returns:
            Response with success status and remember cookie

        Raises:
            ValidationError: If token verification fails
        """
        with transaction.atomic():
            totp_device = default_device(user)
            # Backup codes are in place in case a user's device is lost or unavailable.
            # They can be consumed in any order; each token will be removed from the
            # database as soon as it is used.
            static_device = StaticDevice.objects.filter(user=user).first()

            # Check the token against one device only. A wrong code then counts against that
            # device's throttle alone, and a locked authenticator leaves the backup codes usable.
            if totp_device and not is_backup_code_attempt(token):
                device, other_device = totp_device, static_device
            else:
                device, other_device = static_device, totp_device

            is_allowed, throttle_info = device.verify_is_allowed() if device else (True, None)
            if device and is_allowed and device.verify_token(token):
                if other_device:
                    other_device.throttle_reset()
                if device is static_device:
                    send_two_factor_auth_backup_code_used_email.delay(user.id)
                return self._token_is_valid(request, user, device)

        # Raise after the transaction commits, so the failed attempt verify_token recorded is kept.
        if not is_allowed:
            can_use_backup_code = device is totp_device and static_device and static_device.token_set.exists()
            raise serializers.ValidationError(
                detail=self._too_many_attempts_message(throttle_info, bool(can_use_backup_code)),
                code="2fa_too_many_attempts",
            )
        raise serializers.ValidationError(detail="Invalid authentication code", code="2fa_invalid")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        # Validate session state - keys must exist from login flow
        user_id = request.session.get("user_authenticated_but_no_2fa")
        auth_time = request.session.get("user_authenticated_time")

        if not user_id or auth_time is None:
            raise serializers.ValidationError(
                detail="Invalid 2FA session. Please log in again.",
                code="invalid_2fa_session",
            )

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                detail="Invalid 2FA session. Please log in again.",
                code="invalid_2fa_session",
            )

        expiration_time = auth_time + getattr(settings, "TWO_FACTOR_LOGIN_TIMEOUT", 600)
        if int(time.time()) > expiration_time:
            raise serializers.ValidationError(
                detail="Login attempt has expired. Re-enter username/password.",
                code="2fa_expired",
            )

        # Check if this is a passkey 2FA attempt
        credential_id = request.data.get("credential_id")
        response_data = request.data.get("response")
        if credential_id and response_data:
            return self._handle_passkey_2fa(request, user, credential_id, response_data)

        # TOTP/backup code flow
        token = request.data.get("token")
        if not token:
            raise serializers.ValidationError(
                detail="Either token or passkey credentials required.", code="2fa_missing_credentials"
            )

        return self._handle_totp_2fa(request, user, token)


class TwoFactorPasskeyViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for beginning 2FA passkey authentication.
    Generates a challenge for passkey-based 2FA.
    """

    queryset = User.objects.none()
    permission_classes = (permissions.AllowAny,)

    @action(detail=False, methods=["GET"], url_path="methods")
    def methods(self, request: Request) -> Response:
        """
        Get available 2FA methods for the user in the current 2FA session.
        """
        user_id = request.session.get("user_authenticated_but_no_2fa")
        if not user_id:
            return Response(
                {"error": "No pending 2FA session. Please log in first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        totp_device = default_device(user)
        user_has_passkeys = has_passkeys(user)
        passkeys_enabled_for_2fa = user_has_passkeys and user.passkeys_enabled_for_2fa

        return Response(
            {
                "has_totp": totp_device is not None,
                "has_passkeys": passkeys_enabled_for_2fa,
            }
        )

    @action(detail=False, methods=["POST"], url_path="begin")
    def begin(self, request: Request) -> Response:
        """
        Begin 2FA passkey authentication by generating a challenge.
        """
        from posthog.api.webauthn import WEBAUTHN_2FA_CHALLENGE_KEY

        user_id = request.session.get("user_authenticated_but_no_2fa")
        if not user_id:
            return Response(
                {"error": "No pending 2FA session. Please log in first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if user has passkeys
        if not has_passkeys(user):
            return Response(
                {"error": "No passkeys found for this user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if passkeys are enabled for 2FA
        if not user.passkeys_enabled_for_2fa:
            return Response(
                {"error": "Passkeys are not enabled for 2FA. Please enable them in your settings."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get all verified passkeys for the user
        credentials = WebauthnCredential.objects.filter(user=user, verified=True)

        # Build allow_credentials list
        allow_credentials = [
            PublicKeyCredentialDescriptor(
                id=cred.credential_id,
                transports=[AuthenticatorTransport(t) for t in cred.transports if t],
            )
            for cred in credentials
        ]

        # Generate authentication options
        options = generate_passkey_authentication_options(allow_credentials=allow_credentials)

        # Store challenge in session
        request.session[WEBAUTHN_2FA_CHALLENGE_KEY] = bytes_to_base64url(options.challenge)
        request.session.save()

        mfa_logger.info("webauthn_2fa_begin", user_id=user.pk)

        return Response(json.loads(options_to_json(options)))


def _complete_idp_login(request: Request, user: User, pending: PendingIdPEmailVerification) -> None:
    if _sso_access_refused(request, user):
        raise exceptions.PermissionDenied(ACCOUNT_BLOCKED_DETAIL, code=SECURITY_REFUSAL_CODE)
    strategy = load_strategy(request._request)
    partial = strategy.partial_load(pending["partial_token"])
    if (
        partial is None
        or partial.kwargs.get("user") != user
        or partial.backend != pending["provider"]
        or str(partial.kwargs.get("uid")) != pending["uid"]
        or (partial.kwargs.get("details", {}).get("email") or "").strip().lower() != pending["email"]
        or request.session.get("partial_pipeline_token") != pending["partial_token"]
        or partial.kwargs.get("idp_authenticated_at") != pending["authenticated_at"]
        or partial.kwargs.get("idp_authenticated_identity")
        != idp_identity_key(pending["provider"], pending["issuer"], pending["subject"])
        or not idp_authentication_is_fresh(partial.kwargs.get("idp_authenticated_at"))
        or user.email.strip() != pending["target_email"]
    ):
        raise serializers.ValidationError({"detail": "Please log in again."}, code="no_pending_verification")
    backend = load_backend(strategy, pending["provider"], reverse("social:complete", args=[pending["provider"]]))
    identity = _identity_provider_identity(backend, partial.kwargs.get("details"), partial.kwargs.get("response"))
    if identity != IdPIdentity(provider=pending["provider"], issuer=pending["issuer"], subject=pending["subject"]):
        raise serializers.ValidationError({"detail": "Please log in again."}, code="no_pending_verification")
    if UserSocialAuth.objects.filter(provider=pending["provider"], uid=pending["uid"]).exclude(user=user).exists():
        raise serializers.ValidationError(
            {"detail": "This identity is linked to another account."}, code="identity_linked_elsewhere"
        )
    # nosemgrep: idor-lookup-without-user (the identity comes from the pending session, and its code was just verified)
    IdentityProviderEmailVerification.objects.update_or_create(
        provider=pending["provider"],
        issuer=pending["issuer"],
        subject=pending["subject"],
        defaults={"user": user, "email": pending["email"], "target_email": pending["target_email"]},
    )
    _clear_unverified_local_credentials(user)
    do_complete(backend, _do_login, request=request._request, partial_token=pending["partial_token"])
    if request.session.get("_auth_user_id") != str(user.pk):
        raise serializers.ValidationError({"detail": "Please log in again."}, code="no_pending_verification")


def _require_fresh_idp_challenge(request: Request) -> None:
    pending = request.session.get(CODE_BASED_VERIFICATION_SSO_SESSION_KEY)
    if pending and (
        request.user.is_authenticated
        or not idp_authentication_is_fresh(pending.get("authenticated_at"))
        or code_based_verifier.get_pending_identity(request) is None
    ):
        code_based_verifier.clear_pending(request)
        raise serializers.ValidationError(
            {"detail": "Your sign-in expired. Please log in again."}, code="authentication_expired"
        )


class CodeBasedVerificationSerializer(serializers.Serializer):
    code = serializers.CharField(
        help_text="The 6-digit verification code emailed to the user. Whitespace, invisible characters, "
        "and grouping hyphens are removed and compatibility digits (e.g. fullwidth) are folded to ASCII, "
        "so a copy-pasted code still verifies; anything that isn't then exactly 6 digits is rejected."
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        help_text="Email the code was sent to. Informational; the pending login session identifies the user.",
    )

    def validate_code(self, value: str) -> str:
        # Require exactly 6 digits after normalization so malformed input is rejected outright
        # rather than mining digits out of arbitrary text.
        cleaned = normalize_verification_code(value)
        if not re.fullmatch(r"\d{6}", cleaned):
            raise serializers.ValidationError("Enter the 6-digit code from your email.")
        return cleaned


class CodeBasedVerificationViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    """Verify the emailed login code against the pending login session and complete login."""

    serializer_class = CodeBasedVerificationSerializer
    queryset = User.objects.none()
    permission_classes = (permissions.AllowAny,)
    throttle_classes = [CodeBasedVerificationThrottle]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Verify the 6-digit code against the pending login session and log the user in."""
        invalid_error = serializers.ValidationError(
            {"code": ["This code is invalid or has expired."]}, code="invalid_code"
        )

        if not code_based_verifier.has_pending_code_based_verification(request):
            raise serializers.ValidationError(
                {"detail": "No pending verification. Please log in again."},
                code="no_pending_verification",
            )
        _require_fresh_idp_challenge(request)

        # Reserve this attempt atomically before doing anything else, so concurrent guesses can't all
        # observe the same count and exceed the cap. `attempts` includes the current attempt.
        attempts = code_based_verifier.reserve_attempt(request)
        if attempts > CODE_MAX_ATTEMPTS:
            mfa_logger.warning(
                "Code-based verification locked out",
                user_id=code_based_verifier.get_pending_code_based_verification_user_id(request),
                attempts=attempts,
            )
            LOGIN_CODE_VERIFICATION_COUNTER.labels(result="locked_out").inc()
            code_based_verifier.clear_pending(request)
            raise serializers.ValidationError(
                {"detail": "Too many incorrect attempts. Please log in again."},
                code="too_many_attempts",
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = serializer.validated_data.get("code")
        user_id = code_based_verifier.get_pending_code_based_verification_user_id(request)
        try:
            user = User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            code_based_verifier.clear_pending(request)
            raise invalid_error

        if not code or not code_based_verifier.check_code(request, user, code):
            mfa_logger.warning("Code-based verification attempt failed", user_id=user.pk, attempt=attempts)
            LOGIN_CODE_VERIFICATION_COUNTER.labels(result="invalid").inc()
            raise invalid_error

        # Code valid - invalidate the pending state and complete login.
        sso: PendingIdPEmailVerification | None = request.session.get(CODE_BASED_VERIFICATION_SSO_SESSION_KEY)
        if bool(sso) != bool(code_based_verifier.get_pending_identity(request)):
            code_based_verifier.clear_pending(request)
            raise invalid_error
        if sso and (
            sso.get("user_id") != user.pk
            or sso.get("target_email") != code_based_verifier.get_pending_code_based_verification_target(request)
            or sso.get("issued_at") != code_based_verifier.get_pending_code_based_verification_issued_at(request)
            or code_based_verifier.get_pending_identity(request)
            != idp_identity_key(sso["provider"], sso["issuer"], sso["subject"])
        ):
            code_based_verifier.clear_pending(request)
            raise invalid_error
        code_based_verifier.clear_pending(request)
        if sso:
            _complete_idp_login(request, user, sso)
        else:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            report_user_logged_in(user, social_provider="")
        set_two_factor_verified_in_session(request)
        mfa_logger.info("Code-based verification successful", user_id=user.pk)
        LOGIN_CODE_VERIFICATION_COUNTER.labels(result="success").inc()

        response = Response({"success": True})

        if not sso:
            # Only a password login may skip the code this way. An identity provider login would
            # otherwise grant the remember cookie that exempts the same account's password logins.
            _set_remember_device_cookie(response, user, "code_based_verification")

        if not sso:
            # The SSO notification worker must inspect the previous fingerprint before caching it.
            short_user_agent = get_short_user_agent(request)
            ip_address = get_ip_address(request)
            geoip = get_geoip_properties(ip_address)
            country = geoip.get("$geoip_country_name", "Unknown")
            check_and_cache_login_device(user.id, country, short_user_agent)

        return response

    @action(detail=False, methods=["post"], throttle_classes=[CodeBasedVerificationResendThrottle])
    def resend(self, request: Request) -> Response:
        """Resend a fresh verification code, invalidating the previous one."""
        if not code_based_verifier.has_pending_code_based_verification(request):
            raise serializers.ValidationError(
                {"detail": "No pending verification found."}, code="no_pending_verification"
            )
        _require_fresh_idp_challenge(request)

        try:
            user = User.objects.get(pk=code_based_verifier.get_pending_code_based_verification_user_id(request))
        except User.DoesNotExist:
            raise serializers.ValidationError({"detail": "User not found."}, code="user_not_found")

        # A resend must keep mailing the address the pending code authorizes, or the new code would
        # bind to the account address and no longer verify.
        target_email = code_based_verifier.get_pending_code_based_verification_target(request)
        if not _send_login_code(
            request,
            user,
            is_resend=True,
            target_email=target_email,
            identity=code_based_verifier.get_pending_identity(request),
            asserted_email=(request.session.get(CODE_BASED_VERIFICATION_SSO_SESSION_KEY) or {}).get("email"),
        ):
            raise serializers.ValidationError(
                {"detail": "Could not send verification code."},
                code="code_based_verification_email_failed",
            )
        extend_login_attempt(request, valid_for_seconds=CODE_TTL_SECONDS)

        return Response({"success": True, "message": "Verification code sent"})


class LoginPrecheckViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = LoginPrecheckSerializer
    permission_classes = (permissions.AllowAny,)
    throttle_classes = [] if settings.E2E_TESTING else [LoginPrecheckThrottle]


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField(write_only=True)

    def create(self, validated_data):
        email = validated_data.pop("email")
        # Same lookup login uses, so a reset link can never reach a different account than the
        # password it replaces.
        user = EmailLookupHandler.get_user_by_email(email)

        # Check SSO enforcement (which happens at the domain level)
        if sso_enforcement_for_login_address(email, user):
            raise serializers.ValidationError(
                "Password reset is disabled because SSO login is enforced for this domain.",
                code="sso_enforced",
            )

        if not is_email_available():
            raise serializers.ValidationError(
                "Cannot reset passwords because email is not configured for your instance. Please contact your administrator.",
                code="email_not_available",
            )

        if user:
            user.requested_password_reset_at = datetime.datetime.now(datetime.UTC)
            user.save()
            token = password_reset_token_generator.make_token(user)
            send_password_reset(user.id, token)

        return True


class PasswordResetCompleteSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)

    def to_representation(self, instance):
        if isinstance(instance, dict) and "email" in instance:
            return {"success": True, "email": instance["email"]}
        return {"success": True}

    def create(self, validated_data):
        # Special handling for E2E tests (note we don't actually change anything in the DB, just simulate the response)
        if settings.E2E_TESTING and validated_data["token"] == "e2e_test_token":
            return {"email": "test@posthog.com"}

        try:
            user = User.objects.filter(is_active=True).get(uuid=self.context["view"].kwargs["user_uuid"])
        except (User.DoesNotExist, ValidationError):
            capture_exception(
                Exception("User not found in password reset serializer"),
                {"user_uuid": self.context["view"].kwargs["user_uuid"]},
            )
            raise serializers.ValidationError(
                {"token": ["This reset token is invalid or has expired."]},
                code="invalid_token",
            )

        if not password_reset_token_generator.check_token(user, validated_data["token"]):
            capture_exception(
                Exception("Invalid password reset token in serializer"),
                {"user_uuid": user.uuid, "token": validated_data["token"]},
            )
            raise serializers.ValidationError(
                {"token": ["This reset token is invalid or has expired."]},
                code="invalid_token",
            )
        password = validated_data["password"]
        try:
            validate_password(password, user)
        except ValidationError as e:
            raise serializers.ValidationError({"password": e.messages})

        user.set_password(password)
        user.requested_password_reset_at = None
        # Possessing the unique reset token (only ever delivered by email via
        # send_password_reset) proves the user owns this address, regardless of
        # whether they came in as None (legacy / agentic-provisioned), False
        # (invite-accept, Vercel-provisioned), or True.
        user.is_email_verified = True
        user.save()

        # The reset flow doesn't log the user in, and a reset is the canonical compromise-recovery
        # action, so revoke every existing login session for this user.
        revoke_other_sessions(user, keep_session_key=None)

        report_user_password_reset(user)
        return {"email": user.email}


class PasswordResetViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = PasswordResetSerializer
    permission_classes = (permissions.AllowAny,)
    throttle_classes = [UserPasswordResetThrottle]
    SUCCESS_STATUS_CODE = status.HTTP_204_NO_CONTENT


class PasswordResetCompleteViewSet(NonCreatingViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = PasswordResetCompleteSerializer
    permission_classes = (permissions.AllowAny,)
    SUCCESS_STATUS_CODE = status.HTTP_200_OK

    def get_object(self):
        token = self.request.query_params.get("token")
        user_uuid = self.kwargs.get("user_uuid")

        if not token:
            raise serializers.ValidationError({"token": ["This field is required."]}, code="required")

        # Special handling for E2E tests
        if settings.E2E_TESTING and user_uuid == "e2e_test_user" and token == "e2e_test_token":
            return {"success": True, "token": token}

        try:
            user = User.objects.filter(is_active=True).get(uuid=user_uuid)
        except (User.DoesNotExist, ValidationError):
            capture_exception(
                Exception("User not found in password reset viewset"), {"user_uuid": user_uuid, "token": token}
            )
            raise serializers.ValidationError(
                {"token": ["This reset token is invalid or has expired."]},
                code="invalid_token",
            )

        if not password_reset_token_generator.check_token(user, token):
            capture_exception(
                Exception("Invalid password reset token in viewset"), {"user_uuid": user_uuid, "token": token}
            )
            raise serializers.ValidationError(
                {"token": ["This reset token is invalid or has expired."]},
                code="invalid_token",
            )

        return {"success": True, "token": token}

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().retrieve(request, *args, **kwargs)
        response.status_code = self.SUCCESS_STATUS_CODE
        response.data = None
        return response


class PasswordResetTokenGenerator(DefaultPasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        # Due to type differences between the user model and the token generator, we need to
        # re-fetch the user from the database to get the correct type.
        usable_user: User = User.objects.get(pk=user.pk)
        return f"{user.pk}{user.email}{usable_user.requested_password_reset_at}{timestamp}{usable_user.password}"


password_reset_token_generator = PasswordResetTokenGenerator()


def _sso_reauth_request(strategy: DjangoStrategy) -> HttpRequest | None:
    """The request behind a step-up re-auth of an already signed-in session, or None if it isn't one."""
    if strategy.session_get("reauth") != "true":
        return None

    request = strategy.request
    if not request or not request.user.is_authenticated:
        return None

    return request


def _is_signed_in_github_account_link(strategy: DjangoStrategy, backend: BaseAuth) -> bool:
    request = strategy.request
    return (
        bool(request)
        and request.user.is_authenticated
        and getattr(backend, "name", "") == "github"
        and (strategy.session_get("next") or "").startswith("/account-connected/github-login")
        and _sso_reauth_request(strategy) is None
    )


def social_identity_matches_session(
    strategy: DjangoStrategy,
    backend: Any,
    details: dict[str, Any] | None = None,
    user: User | None = None,
    social: Any = None,
    **kwargs: Any,
) -> None:
    request = strategy.request
    if not request or not request.user.is_authenticated or social is not None:
        return

    if _is_signed_in_github_account_link(strategy, backend):
        return

    identity_email = ((details or {}).get("email") or "").lower()
    if user is None or user.pk != request.user.pk or identity_email != request.user.email.lower():
        logger.warning(
            "SSO identity mismatch for authenticated session",
            backend=getattr(backend, "name", ""),
            session_user_id=request.user.pk,
        )
        raise AuthFailed(backend, "reauth_user_mismatch")


def _github_email_is_verified(backend: GithubOAuth2, access_token: str, email: str) -> bool:
    try:
        emails: object = backend.get_json(
            urljoin(backend.api_url(), "user/emails"), headers={"Authorization": f"token {access_token}"}
        )
    except (RequestException, AuthConnectionError, ValueError) as error:
        logger.warning("github_email_verification_lookup_failed", exc_info=True)
        raise AuthFailed(backend, GITHUB_EMAIL_LOOKUP_ERROR) from error
    if not isinstance(emails, list):
        logger.warning("github_email_verification_lookup_unexpected_response")
        raise AuthFailed(backend, GITHUB_EMAIL_LOOKUP_ERROR)
    return any(
        isinstance(entry, dict)
        and entry.get("verified") is True
        and str(entry.get("email", "")).lower() == email.lower()
        for entry in emails
    )


def social_email_verified_by_provider(
    strategy: DjangoStrategy,
    backend: BaseAuth,
    details: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
    social: UserSocialAuth | None = None,
    **kwargs: Any,
) -> None:
    # A linked identity resolves by its provider uid, and a signed-in account connect is keyed to the
    # session. Every other flow, re-authentication included, trusts the email address.
    if social is not None or _is_signed_in_github_account_link(strategy, backend):
        return

    if backend.name == "oidc":
        # MultitenantOIDCAuth validates the subject and verified organization domain instead of this claim.
        return

    response = response or {}
    email = (details or {}).get("email") or ""
    if isinstance(backend, GithubOAuth2):
        # The GitHub backend picks the primary address from /user/emails without its `verified` flag,
        # and GitHub lets an unverified address be primary.
        is_verified = not email or _github_email_is_verified(backend, response.get("access_token", ""), email)
    elif backend.name == "google-oauth2":
        is_verified = response.get("email_verified") is True
    else:
        is_verified = response.get("email_verified") is not False

    if not is_verified:
        logger.warning("social_login_unverified_provider_email", backend=backend.name)
        raise AuthFailed(backend, UNVERIFIED_SOCIAL_EMAIL_ERROR)


def social_reauth(
    strategy: DjangoStrategy,
    backend,
    details: dict[str, Any] | None = None,
    user: User | None = None,
    social: Any = None,
    **kwargs,
) -> None:
    """Turn away a step-up re-auth that isn't the signed-in user.

    Runs right after `social_user`, so a mismatched identity is rejected before `associate_user` can
    link it to the signed-in account or `social_create_user` can provision anything. The step-up
    itself is granted at the end of the pipeline, by `social_reauth_complete`.
    """
    request = _sso_reauth_request(strategy)
    if not request:
        return

    # An identity that isn't associated with anyone yet resolves to whoever is signed in, so without
    # an email check `associate_user` would silently link a stranger's IdP account to this account.
    identity_email = ((details or {}).get("email") or "").lower()
    identity_is_signed_in_user = (
        user is not None and user.pk == request.user.pk and (social is not None or identity_email == user.email.lower())
    )

    if not identity_is_signed_in_user:
        logger.warning(
            "SSO re-authentication identity mismatch",
            backend=getattr(backend, "name", ""),
            session_user_id=request.user.pk,
        )
        raise AuthFailed(backend, "reauth_user_mismatch")


def social_access_rules_allow(
    strategy: DjangoStrategy, backend: BaseAuth, user: User | None = None, **kwargs: Any
) -> None:
    """Refuse an SSO login for an account that an enforced access rule blocks, before a session starts."""
    if user is None:
        # A new account is checked where it is created: the signup serializer, or the SSO invite
        # and verified-domain joins in posthog/api/signup.py.
        return
    if _sso_access_refused(strategy.request, user):
        raise AuthFailed(backend, SECURITY_REFUSAL_CODE)


def _sso_access_refused(request: HttpRequest, user: User) -> bool:
    try:
        return security_access_refused(
            SecuritySubject(email=user.email, user_uuid=str(user.uuid), ip=get_trusted_client_ip(request)),
            SecuritySurface.APP,
            call_site="sso_login",
        )
    except Exception:
        logger.exception("security_access_check_site_failed", call_site="sso_login")
        return False


@frozen
class IdPIdentity:
    provider: str
    issuer: str
    subject: str


def _identity_provider_identity(
    backend: BaseAuth, details: dict[str, Any] | None, response: dict[str, Any] | None
) -> IdPIdentity | None:
    """Bind SAML proof to its signing certificate because an entity ID can survive an IdP replacement."""
    if backend.name == "oidc":
        try:
            oidc_config = cast("MultitenantOIDCAuth", backend).identity_provider_config
        except AuthFailed:
            return None
        issuer = oidc_config.oidc_issuer_url.rstrip("/")
    else:
        relay_state = (response or {}).get("idp_name")
        if not relay_state:
            return None
        config = IdentityProviderConfig.objects.filter(saml_relay_state=relay_state).first()
        if config is None or not config.saml_entity_id or not config.saml_x509_cert:
            return None
        issuer = cast("MultitenantSAMLAuth", backend).authentication_issuer or saml_identity_issuer(
            config.saml_entity_id, config.saml_x509_cert
        )

    subject = cast("MultitenantOIDCAuth | MultitenantSAMLAuth", backend).get_identity_subject(
        details or {}, response or {}
    )
    if not issuer or not subject:
        return None
    return IdPIdentity(provider=backend.name, issuer=issuer, subject=subject)


def social_require_idp_email_verification(
    strategy: DjangoStrategy,
    backend: BaseAuth,
    uid: str | None = None,
    user: User | None = None,
    details: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
    **kwargs: Any,
) -> HttpResponse | None:
    """Hold a login until the resolved account's mailbox approves its identity.

    Runs before `associate_user`, so an unproven identity is never linked to the account, and a
    response from a pipeline step makes `do_complete` return it instead of starting a session.
    """
    if backend.name not in IDP_SSO_BACKENDS:
        return None
    if _sso_reauth_request(strategy):
        if user is None or not UserSocialAuth.objects.filter(user=user, provider=backend.name, uid=uid).exists():
            raise AuthFailed(backend, "reauth_user_mismatch")
        return None
    identity = _identity_provider_identity(backend, details, response)
    email = ((details or {}).get("email") or "").strip().lower()
    if user is None or not uid or identity is None or not email:
        return redirect(sso_failure_redirect_url(strategy.request, "improperly_configured_sso"))

    target_email = user.email.strip()
    if IdentityProviderEmailVerification.objects.filter(
        user=user,
        provider=identity.provider,
        issuer=identity.issuer,
        subject=identity.subject,
        email=email,
        target_email=target_email,
    ).exists():
        _clear_unverified_local_credentials(user)
        return None

    request = strategy.request
    authenticated_at = kwargs.get("idp_authenticated_at")
    if not idp_authentication_is_fresh(authenticated_at):
        raise AuthStateForbidden(backend)
    if backend.name == "saml" and kwargs.get("saml_browser_verified") is not True:
        restart = {"email": email, "idp_config": str((response or {})["idp_name"])}
        if next_url := get_safe_next_url(strategy.session_get("next"), request):
            restart["next"] = next_url
        return redirect(f"{reverse('social:begin', args=['saml'])}?{urlencode(restart)}")

    try:
        sent = _send_login_code(
            request,
            user,
            target_email=target_email,
            identity=idp_identity_key(identity.provider, identity.issuer, identity.subject),
            asserted_email=email,
        )
    except LoginCodeEmailUndeliverable:
        logger.warning("idp_email_verification_code_undeliverable", user_id=user.pk, backend=backend.name)
        sent = False
    if not sent:
        code_based_verifier.clear_pending(request)
        return redirect(sso_failure_redirect_url(request, "sso_verification_email_failed"))

    request.session[CODE_BASED_VERIFICATION_SSO_SESSION_KEY] = PendingIdPEmailVerification(
        provider=identity.provider,
        issuer=identity.issuer,
        subject=identity.subject,
        uid=str(uid),
        email=email,
        target_email=target_email,
        authenticated_at=cast(int, authenticated_at),
        user_id=user.pk,
        issued_at=cast(int, code_based_verifier.get_pending_code_based_verification_issued_at(request)),
        partial_token=kwargs["current_partial"].token,
    )
    query = {"code_verification_pending": "1", "email": target_email}
    next_url = strategy.session_get("next") or ""
    if next_url:
        query["next"] = next_url
    return redirect(f"/login?{urlencode(query)}")


def social_reauth_complete(strategy: DjangoStrategy, backend, user: User | None = None, **kwargs) -> None:
    """Grant the step-up, once every other pipeline step has accepted the flow.

    `sso_login` doesn't flush the session for a re-auth, which means `do_complete` takes its
    already-authenticated path and never calls `login()` - so the freshness stamp and the audit entry
    that `login()` would have triggered have to happen here, or the modal would reopen forever.

    This runs last because a step that returns a response aborts the pipeline - domain enforcement in
    `social_create_user` does exactly that - and a refused re-auth must not leave a fresh window, a
    cleared step-up flag, or a `logged_in` entry behind.
    """
    request = _sso_reauth_request(strategy)
    if not request or user is None or user.pk != request.user.pk:
        return

    # Rotate the key the way `login()` would on a fresh sign-in. A step-up window is exactly what a
    # copied session cookie wants, so the identifier that existed before it has to stop working. The
    # session data - and with it the signed-in user - survives the rotation.
    request.session.cycle_key()
    request.session[settings.SESSION_LAST_REAUTH_AT_KEY] = time.time()
    request.session.pop(settings.SESSION_STEP_UP_REQUIRED_KEY, None)

    backend_name = getattr(backend, "name", "")
    try:
        signal_handlers.log_login_activity(
            user,
            request,
            login_method=str(AUTH_BACKEND_DISPLAY_NAMES.get(backend_name, "Unknown")),
            reauth=True,
        )
    except Exception as e:
        # Matching `log_user_login_activity`: a failed audit write must not fail the re-auth itself
        logger.exception("Failed to log SSO re-authentication activity", user_id=user.id, error=e)
        capture_exception(e)


def social_grant_staff_to_google_workspace_members(
    backend: BaseAuth, response: dict[str, Any], user: User | None = None, **kwargs: Any
) -> None:
    """
    Employees on dev ask for Django staff. This step grants it when they log in to dev with Google,
    so they do not have to ask. The `hd` claim confirms that our Google Workspace manages the account.
    """
    if (
        settings.CLOUD_DEPLOYMENT == "DEV"
        and backend.name == "google-oauth2"
        and user is not None
        and not user.is_staff
        and user.email.endswith(POSTHOG_INTERNAL_EMAIL_SUFFIX)
        and response.get("hd") in settings.ADMIN_AUTH_GOOGLE_ALLOWED_DOMAINS
    ):
        user.is_staff = True
        user.save(update_fields=["is_staff"])


def _notify_social_login(request: HttpRequest, user: User, backend_name: str) -> None:
    report_user_logged_in(user, social_provider=backend_name)
    if not has_valid_known_device_cookie(request, user):
        login_from_new_device_notification.delay(
            user.id, timezone.now(), get_short_user_agent(request), get_ip_address(request), backend_name
        )


def social_login_notification(
    strategy: DjangoStrategy, backend, user: User | None = None, is_new: bool = False, **kwargs
):
    """Final pipeline step to notify on OAuth/SAML login"""
    if not user:
        return

    if strategy.session_get("reauth") == "true":
        return

    # Trigger notification and event only on login
    if not is_new:
        _notify_social_login(strategy.request, user, getattr(backend, "name", ""))
