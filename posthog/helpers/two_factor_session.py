import json
import time
import datetime
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.http import HttpRequest
from django.utils.crypto import constant_time_compare, salted_hmac

import structlog
import posthoganalytics
from loginas.utils import is_impersonated_session
from posthoganalytics import capture_exception
from prometheus_client import Counter
from rest_framework.exceptions import PermissionDenied
from two_factor.utils import default_device

from posthog.cloud_utils import is_dev_mode
from posthog.email import is_email_available, is_http_email_service_available
from posthog.helpers.email_utils import ESPSuppressionReason, check_esp_suppression
from posthog.models.user import User
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.redis import get_client
from posthog.settings.web import AUTHENTICATION_BACKENDS

CODE_BASED_VERIFICATION_BYPASS_REDIS_KEY = "code_based_verification_bypass_emails"


def is_code_based_verification_bypass(email: str) -> bool:
    return bool(get_client().sismember(CODE_BASED_VERIFICATION_BYPASS_REDIS_KEY, email.lower()))


def add_code_based_verification_bypass(email: str) -> None:
    get_client().sadd(CODE_BASED_VERIFICATION_BYPASS_REDIS_KEY, email.lower())


def remove_code_based_verification_bypass(email: str) -> None:
    get_client().srem(CODE_BASED_VERIFICATION_BYPASS_REDIS_KEY, email.lower())


# Global kill-switch: when this Redis key is present, code-based verification is skipped for every
# user (e.g. while transactional email delivery is down and the verification link can't be
# delivered). The key carries the reason/actor/timestamp and a mandatory TTL so it auto-re-enables.
# Only the email factor is affected — TOTP and passkey 2FA are gated earlier in the login flow.
CODE_BASED_VERIFICATION_GLOBAL_DISABLE_REDIS_KEY = "code_based_verification_global_disable"
MAX_CODE_BASED_VERIFICATION_GLOBAL_DISABLE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def is_code_based_verification_globally_disabled() -> bool:
    # Fail closed: if Redis is unreachable, keep code-based verification enforced (the secure default) rather than
    # silently dropping the second factor — and never let a Redis hiccup break the login flow.
    try:
        return bool(get_client().exists(CODE_BASED_VERIFICATION_GLOBAL_DISABLE_REDIS_KEY))
    except Exception:
        mfa_logger.exception(
            "Failed to read code-based verification global disable flag; keeping code-based verification enforced"
        )
        return False


def get_code_based_verification_global_disable() -> Optional[dict]:
    try:
        client = get_client()
        raw = client.get(CODE_BASED_VERIFICATION_GLOBAL_DISABLE_REDIS_KEY)
        if not raw:
            return None
        data = json.loads(raw)
        ttl = client.ttl(CODE_BASED_VERIFICATION_GLOBAL_DISABLE_REDIS_KEY)
        data["expires_in_seconds"] = ttl if isinstance(ttl, int) and ttl > 0 else None
        return data
    except Exception:
        mfa_logger.exception("Failed to read code-based verification global disable state")
        return None


def set_code_based_verification_global_disable(reason: str, ttl_seconds: int, disabled_by: str) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reason is required to disable code-based verification.")
    if not 0 < ttl_seconds <= MAX_CODE_BASED_VERIFICATION_GLOBAL_DISABLE_TTL_SECONDS:
        raise ValueError(
            f"TTL must be between 1 second and {MAX_CODE_BASED_VERIFICATION_GLOBAL_DISABLE_TTL_SECONDS} seconds (7 days)."
        )
    payload = json.dumps(
        {
            "reason": reason,
            "disabled_by": disabled_by,
            "disabled_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
    )
    get_client().set(CODE_BASED_VERIFICATION_GLOBAL_DISABLE_REDIS_KEY, payload, ex=ttl_seconds)


def clear_code_based_verification_global_disable() -> None:
    get_client().delete(CODE_BASED_VERIFICATION_GLOBAL_DISABLE_REDIS_KEY)


def has_passkeys(user: User) -> bool:
    """
    Returns True if the user has any verified passkeys, False otherwise.

    Unlike TOTP devices which have a single default device, users can have multiple passkeys
    and they're all equivalent. This function simply checks if the user has any verified passkeys.

    Args:
        user: The user to check for passkeys

    Returns:
        bool: True if user has verified passkeys, False otherwise
    """
    return WebauthnCredential.objects.filter(user=user, verified=True).exists()


mfa_logger = structlog.get_logger("posthog.auth.mfa")

# One counter for the whole code-based login-verification flow, sliced by transition. Lets Grafana
# derive send volume, delivery failures, completion rate (success / sent), invalid-code rate and
# lockout rate, and alert on any of them.
LOGIN_CODE_VERIFICATION_COUNTER = Counter(
    "login_code_verification_total",
    "Transitions in the code-based login-verification flow.",
    labelnames=["result"],  # sent | resent | send_failed | success | invalid | locked_out
)


# Enforce Two-Factor Authentication only on sessions created after this date
TWO_FACTOR_ENFORCEMENT_FROM_DATE = datetime.datetime(2025, 9, day=22, hour=13)

TWO_FACTOR_VERIFIED_SESSION_KEY = "two_factor_verified"

WHITELISTED_PATHS = [
    "/api/users/@me/two_factor_start_setup/",
    "/api/users/@me/two_factor_validate/",
    "/api/users/@me/two_factor_status/",
    "/api/users/@me/two_factor_backup_codes/",
    "/api/users/@me/two_factor_disable/",
    "/logout/",
    "/api/logout/",
    "/api/login/",
    "/api/login/token/",
    "/api/login/code-based-verification/",
    "/api/users/@me/",
    "/_health/",
]

WHITELISTED_PREFIXES = [
    "/static/",
    "/uploaded_media/",
    "/api/instance_status",
    "/api/signup",
    "/api/social_signup",
    "/login/google-oauth2",
    "/login/github",
    "/login/gitlab",
    "/login/saml",
    "/complete/google-oauth2",
    "/complete/github",
    "/complete/gitlab",
    "/complete/saml",
    "/api/saml/metadata",
]


def set_two_factor_verified_in_session(request: HttpRequest, verified: bool = True) -> None:
    if verified:
        request.session[TWO_FACTOR_VERIFIED_SESSION_KEY] = True
    else:
        clear_two_factor_session_flags(request)


def is_two_factor_verified_in_session(request: HttpRequest) -> bool:
    if not request.session.get(TWO_FACTOR_VERIFIED_SESSION_KEY):
        return False

    if is_two_factor_session_expired(request):
        clear_two_factor_session_flags(request)
        return False

    return True


def clear_two_factor_session_flags(request: HttpRequest) -> None:
    request.session.pop(TWO_FACTOR_VERIFIED_SESSION_KEY, None)


def is_two_factor_session_expired(request: HttpRequest) -> bool:
    session_created_at = request.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY)
    if not session_created_at:
        return True

    return time.time() - session_created_at > settings.SESSION_COOKIE_AGE


def enforce_two_factor(request, user):
    """
    Enforce Two-Factor Authentication requirements for authenticated users in organizations that require it.
    Excludes paths that are whitelisted and domains that have SSO enforcement enabled.
    """
    if is_path_whitelisted(request.path):
        return

    # We currently don't enforce 2FA for any SSO-authenticated users, as we depend on the SSO provider to handle 2FA
    # TODO: This will soon be made configurable
    if is_sso_authentication_backend(request._request):
        return

    organization = getattr(user, "organization", None)
    if organization and organization.enforce_2fa:
        # Same as above, we don't enforce 2FA on SSO-enforced domains, we depend on the SSO provider to handle 2FA
        # TODO: This will soon be made configurable
        if is_domain_sso_enforced(request._request):
            return

        if not is_two_factor_enforcement_in_effect(request._request):
            return

        if is_impersonated_session(request._request):
            return

        device = default_device(user)
        user_has_passkeys = has_passkeys(user)
        passkeys_enabled_for_2fa = user_has_passkeys and user.passkeys_enabled_for_2fa
        if not device and not passkeys_enabled_for_2fa:
            raise PermissionDenied(detail="2FA setup required", code="two_factor_setup_required")

        if not is_two_factor_verified_in_session(request._request):
            raise PermissionDenied(detail="2FA verification required", code="two_factor_verification_required")


def is_path_whitelisted(path):
    """
    Check if the request path should bypass Two-Factor Authentication enforcement.
    """
    if path in WHITELISTED_PATHS:
        return True

    for prefix in WHITELISTED_PREFIXES:
        if path.startswith(prefix):
            return True

    return False


def is_two_factor_enforcement_in_effect(request: HttpRequest):
    session_created_at = request.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY)

    if not session_created_at:
        return False

    return datetime.datetime.fromtimestamp(session_created_at) >= TWO_FACTOR_ENFORCEMENT_FROM_DATE


def is_domain_sso_enforced(request: HttpRequest):
    from posthog.models.organization_domain import OrganizationDomain

    if not hasattr(request.user, "email"):
        return False

    return bool(OrganizationDomain.objects.get_sso_enforcement_for_email_address(request.user.email))


def is_sso_authentication_backend(request: HttpRequest):
    SSO_AUTHENTICATION_BACKENDS = []
    NON_SSO_AUTHENTICATION_BACKENDS = [
        "axes.backends.AxesBackend",
        "django.contrib.auth.backends.ModelBackend",
        "posthog.auth.WebauthnBackend",
    ]

    if not hasattr(request, "session"):
        return False

    # Check if we're in EE, if yes, use the EE settings, otherwise use the posthog settings
    try:
        from ee import settings

        SSO_AUTHENTICATION_BACKENDS = settings.AUTHENTICATION_BACKENDS
    except ImportError:
        SSO_AUTHENTICATION_BACKENDS = AUTHENTICATION_BACKENDS

    # Remove the non-SSO backends from the list
    SSO_AUTHENTICATION_BACKENDS = list(set(SSO_AUTHENTICATION_BACKENDS) - set(NON_SSO_AUTHENTICATION_BACKENDS))

    return request.session.get("_auth_user_backend") in SSO_AUTHENTICATION_BACKENDS


CODE_LENGTH = 6
CODE_TTL_SECONDS = 600  # 10 minutes
CODE_MAX_ATTEMPTS = 5
# Failed-attempt budget for a pending login is tracked in Redis so the cap is enforced atomically
# (INCR) rather than via a raceable session read-modify-write, which parallel guesses could sidestep.
CODE_ATTEMPTS_REDIS_KEY_PREFIX = "code_based_verification_attempts"


class CodeBasedVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Derive a short numeric login-verification code from the same secret-keyed,
    per-user hash the framework uses for password-reset tokens. The code is pinned to
    the login attempt's issuance time, valid for CODE_TTL_SECONDS, and rotates
    automatically on login, password change, email change, or deactivation."""

    def make_code(self, user: AbstractBaseUser, issued_at: int) -> str:
        """Deterministic CODE_LENGTH-digit code for this user and issuance time."""
        digest = salted_hmac(
            self.key_salt,
            self._make_hash_value(user, issued_at),
            secret=self.secret,
            algorithm=self.algorithm,
        ).hexdigest()
        return f"{int(digest, 16) % (10**CODE_LENGTH):0{CODE_LENGTH}d}"

    def check_code(self, user: AbstractBaseUser, code: str, issued_at: int) -> bool:
        """Constant-time compare against the expected code, rejecting expired codes.

        Brute-force resistance does not come from the code's entropy (6 digits is
        guessable) but from the caller gating this behind a password-authenticated
        pending session plus a hard attempt cap.
        """
        if not (user and code and issued_at):
            return False
        if int(time.time()) - issued_at > CODE_TTL_SECONDS:
            return False
        return constant_time_compare(self.make_code(user, issued_at), code)

    def _make_hash_value(self, user: AbstractBaseUser, timestamp: int) -> str:
        """Include last_login and is_active to invalidate tokens after use or deactivation."""
        from posthog.models.user import User

        usable_user: User = User.objects.get(pk=user.pk)
        login_timestamp = "" if user.last_login is None else user.last_login.replace(microsecond=0, tzinfo=None)
        return f"{usable_user.pk}{usable_user.email}{usable_user.password}{usable_user.is_active}{login_timestamp}{timestamp}"


code_based_verification_token_generator = CodeBasedVerificationTokenGenerator()


@dataclass
class CodeBasedVerificationCheckResult:
    should_send: bool
    suppression_bypassed: bool = False
    suppression_reason: Optional[str] = None
    suppression_cached: bool = False


class CodeBasedVerifier:
    def _capture_suppression_bypass_event(self, user: User, reason: str, cached: bool) -> None:
        try:
            posthoganalytics.capture(
                distinct_id=str(user.distinct_id),
                event="code_based_verification_bypassed_due_to_suppression",
                properties={
                    "reason": reason,
                    "cached": cached,
                },
            )
        except Exception as e:
            mfa_logger.warning(
                "Failed to capture code-based verification suppression bypass event",
                user_id=user.pk,
                error=str(e),
            )

    def should_send_code_based_verification(self, user: User) -> CodeBasedVerificationCheckResult:
        if is_code_based_verification_globally_disabled():
            return CodeBasedVerificationCheckResult(should_send=False)

        if is_dev_mode() and not settings.TEST:
            return CodeBasedVerificationCheckResult(should_send=False)

        if not is_email_available(with_absolute_urls=True):
            return CodeBasedVerificationCheckResult(should_send=False)

        if not is_http_email_service_available():
            mfa_logger.info(
                "Code-based verification bypassed - HTTP email service not configured",
                user_id=user.pk,
            )
            self._capture_suppression_bypass_event(user, ESPSuppressionReason.NO_EMAIL_HTTP_SERVICE, False)
            return CodeBasedVerificationCheckResult(
                should_send=False,
                suppression_bypassed=True,
                suppression_reason=ESPSuppressionReason.NO_EMAIL_HTTP_SERVICE,
                suppression_cached=False,
            )

        if is_code_based_verification_bypass(user.email):
            mfa_logger.info("Code-based verification bypassed via admin bypass list", user_id=user.pk)
            return CodeBasedVerificationCheckResult(should_send=False)

        suppression_result = check_esp_suppression(user.email)
        if suppression_result.is_suppressed:
            reason = suppression_result.reason or ""
            from_cache = suppression_result.from_cache
            mfa_logger.info(
                "Code-based verification bypassed due to ESP suppression",
                user_id=user.pk,
                reason=reason,
                cached=from_cache,
            )
            self._capture_suppression_bypass_event(user, reason, from_cache)
            return CodeBasedVerificationCheckResult(
                should_send=False,
                suppression_bypassed=True,
                suppression_reason=reason,
                suppression_cached=from_cache,
            )

        return CodeBasedVerificationCheckResult(should_send=True)

    def create_and_send_code_based_verification(
        self, request: HttpRequest, user: User, *, is_resend: bool = False
    ) -> bool:
        from posthog.tasks import email

        if not self.should_send_code_based_verification(user).should_send:
            return False

        try:
            issued_at = int(time.time())
            code = code_based_verification_token_generator.make_code(user, issued_at)
            email.send_code_based_verification(user.pk, code)
            request.session["code_based_verification_pending_user_id"] = user.pk
            request.session["code_based_verification_issued_at"] = issued_at
            # Resends must not reset the failed-attempt counter, otherwise the attempt cap could be
            # sidestepped by guessing up to the limit, resending, and repeating - letting the 6-digit
            # code be brute-forced in batches. The attempt budget is per pending login, not per code,
            # so only a fresh initial send (not a resend) clears it.
            if not is_resend:
                self._reset_attempts(user.pk)
            LOGIN_CODE_VERIFICATION_COUNTER.labels(result="resent" if is_resend else "sent").inc()
            mfa_logger.info(
                "Code-based verification email sent",
                user_id=user.pk,
                user_last_login=str(user.last_login) if user.last_login else None,
            )
            return True
        except Exception as e:
            LOGIN_CODE_VERIFICATION_COUNTER.labels(result="send_failed").inc()
            mfa_logger.exception(
                "Code-based verification email failed",
                user_id=user.pk,
                error=str(e),
            )
            capture_exception(Exception(f"Code-based verification email failed: {e}"))
            return False

    def has_pending_code_based_verification(self, request: HttpRequest) -> bool:
        return request.session.get("code_based_verification_pending_user_id") is not None

    def get_pending_code_based_verification_user_id(self, request: HttpRequest) -> int | None:
        user_id: int | None = request.session.get("code_based_verification_pending_user_id")
        return user_id

    def get_pending_code_based_verification_issued_at(self, request: HttpRequest) -> int | None:
        return request.session.get("code_based_verification_issued_at")

    def check_code(self, request: HttpRequest, user: User, code: str) -> bool:
        issued_at = self.get_pending_code_based_verification_issued_at(request)
        if not issued_at:
            return False
        return code_based_verification_token_generator.check_code(user, code, issued_at)

    @staticmethod
    def _attempts_redis_key(user_id: int) -> str:
        return f"{CODE_ATTEMPTS_REDIS_KEY_PREFIX}:{user_id}"

    def _reset_attempts(self, user_id: int) -> None:
        try:
            get_client().delete(self._attempts_redis_key(user_id))
        except Exception:
            mfa_logger.exception("Failed to reset code-based verification attempt counter", user_id=user_id)

    def reserve_attempt(self, request: HttpRequest) -> int:
        """Atomically count this verification attempt against the pending login's budget.

        Returns the running attempt total (including this one) so the caller can reject once it
        exceeds CODE_MAX_ATTEMPTS. Backed by a Redis INCR keyed on the pending user id, so parallel
        guesses can't all read the same pre-increment value and slip past the cap. Fails open on a
        Redis error (returns 0) to keep login working - the per-user verify throttle is the backstop.
        """
        user_id = self.get_pending_code_based_verification_user_id(request)
        if not user_id:
            return 0
        try:
            client = get_client()
            count = int(client.incr(self._attempts_redis_key(user_id)))
            client.expire(self._attempts_redis_key(user_id), CODE_TTL_SECONDS)
            return count
        except Exception:
            mfa_logger.exception(
                "Failed to reserve code-based verification attempt; allowing (throttle still applies)",
                user_id=user_id,
            )
            return 0

    def clear_pending(self, request: HttpRequest) -> None:
        user_id = self.get_pending_code_based_verification_user_id(request)
        if user_id:
            self._reset_attempts(user_id)
        for key in (
            "code_based_verification_pending_user_id",
            "code_based_verification_issued_at",
            "code_based_verification_attempts",
        ):
            request.session.pop(key, None)


code_based_verifier = CodeBasedVerifier()
