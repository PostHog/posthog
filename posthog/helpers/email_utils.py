"""
Email-related helpers: address normalization, user lookup by email, and
display-name / message validation.
"""

import re
import html
import string
import unicodedata
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Optional, cast, overload

from django.core.exceptions import MultipleObjectsReturned
from django.db.models import CharField, F, Func, Q, QuerySet, Value
from django.db.models.functions import Lower, Replace

import re2
import structlog
import posthoganalytics
from rest_framework import serializers

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


# The lookbehind and the possessive repeats scan each run of scheme characters once, which keeps the scan linear.
_URL_SCHEME_RE = re.compile(
    r"(?<![a-z0-9+.\-])[0-9+.\-]*+[a-z][a-z0-9+.\-]*+://"
    r"|\b(?:javascript|data|vbscript|file|ftp|mailto|tel|sms):"
    r"|www\.",
    re.IGNORECASE,
)
# re2 keeps the scan linear. Do not limit the label count to get this with `re`, because a match
# would then stop inside a long chain and leave the domain at its end linkable.
# re2 case folding excludes `ı` and `İ`, so the pattern names them. Its `\b` treats them as non-word
# characters, so the pattern has no `\b`. Without `\b`, some text gets an extra invisible defang.
_BARE_DOMAIN_RE = re2.compile(
    r"(?i)(?:[a-z0-9\x{130}\x{131}](?:[a-z0-9\x{130}\x{131}\-]{0,61}[a-z0-9\x{130}\x{131}])?\.)+"
    r"[a-z\x{130}\x{131}]{2,24}"
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f\u0085\u2028\u2029]")
_NON_NEWLINE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u0085\u2028\u2029]")
_BRACKET_RE = re.compile(r"[<>]")
# Includes lone surrogates, because re2 raises UnicodeEncodeError on them.
_INVISIBLE_CHAR_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\ud800-\udfff]")

_URL_ERROR = "URLs are not allowed in this field."
_CONTROL_ERROR = "Line breaks and control characters are not allowed in this field."
_BRACKET_ERROR = "Angle brackets are not allowed in this field."
_INVISIBLE_ERROR = "Invisible or direction-override characters are not allowed in this field."


def _check_shared(value: str) -> None:
    """
    Run the checks shared between display names and message bodies against an
    NFKC-normalized copy of `value`. Normalization folds fullwidth / compat
    variants (e.g. `ｈｔｔｐ：／／` \u2192 `http://`) before regex matching.
    """
    normalized = unicodedata.normalize("NFKC", value)
    if _INVISIBLE_CHAR_RE.search(normalized):
        raise serializers.ValidationError(_INVISIBLE_ERROR, code="invalid_invisible_char")
    if _BRACKET_RE.search(normalized):
        raise serializers.ValidationError(_BRACKET_ERROR, code="invalid_bracket")
    if _URL_SCHEME_RE.search(normalized):
        raise serializers.ValidationError(_URL_ERROR, code="invalid_url")


@overload
def validate_display_name(value: str) -> str: ...


@overload
def validate_display_name(value: None) -> None: ...


def validate_display_name(value: str | None) -> str | None:
    """
    Validate identity fields (`first_name`, `last_name`, organization name,
    invite recipient name). Rejects URL schemes (`https://`, `javascript:`,
    `www.`), line breaks, control characters, angle brackets, and zero-width /
    bidi characters. Bare domains (`google.com`) are allowed — users
    legitimately set those as org names, and `sanitize_email_string` defangs
    them at email render time. Returns the stripped value; empty / blank input
    passes through.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return stripped
    if _CONTROL_CHAR_RE.search(stripped):
        raise serializers.ValidationError(_CONTROL_ERROR, code="invalid_control_char")
    _check_shared(stripped)
    return stripped


def validate_message_body(value: str | None) -> str | None:
    """
    Validate a free-text message body. Newlines and tabs are allowed; URL
    schemes (`http://`, `javascript:`, `www.`, ...), non-newline control
    chars, angle brackets, and invisible chars are not. Bare domains are
    permitted so messages like "see the foo.py file" stay usable.
    """
    if value is None:
        return None
    if _NON_NEWLINE_CONTROL_RE.search(value):
        raise serializers.ValidationError(_CONTROL_ERROR, code="invalid_control_char")
    _check_shared(value)
    return value


def _extract_error_code(err: serializers.ValidationError) -> str:
    """
    Pull the first `code` off a DRF ValidationError. `err.detail` is a union
    of ErrorDetail | list | dict (when raised from a serializer); for the
    single-field validators in this module we always raise the list form, but
    narrow defensively so mypy is happy and we don't crash if a caller hands
    us something unexpected.
    """
    detail = err.detail
    if isinstance(detail, list) and detail:
        first = detail[0]
        return getattr(first, "code", "invalid") or "invalid"
    if isinstance(detail, dict) and detail:
        first = next(iter(detail.values()))
        if isinstance(first, list) and first:
            first = first[0]
        return getattr(first, "code", "invalid") or "invalid"
    return getattr(detail, "code", "invalid") or "invalid"


def _sanitize(
    value: str | None,
    *,
    validator: Callable[[str | None], str | None],
    log_event: str,
    fallback: str,
    context: Optional[dict] = None,
) -> str:
    """
    Core sanitize-with-fallback flow shared by `sanitize_display_name` and
    `sanitize_message_body`. Runs `validator`; on a ValidationError or a
    falsy result (None / empty / whitespace-only, depending on the validator),
    returns `fallback` and logs the rejection with `context` for diagnostics.
    """
    try:
        validated = validator(value)
    except serializers.ValidationError as err:
        logger.info(
            log_event,
            error_code=_extract_error_code(err),
            fallback=fallback,
            **(context or {}),
        )
        return fallback
    return validated or fallback


# `validate_display_name` is `@overload`-decorated to express the None-in / None-out
# relationship at call sites; mypy then can't match the overloaded type against the plain
# `Callable[[str | None], str | None]` signature `_sanitize` expects. Cast once here —
# `_sanitize` always passes through the `str | None` overload at runtime.
_Validator = Callable[[Optional[str]], Optional[str]]

# Display-name fallback for identity fields (organization name, inviter / invitee first name).
# Use in email-sending tasks where dropping the email entirely on a bad legacy value (e.g. an
# organisation name that happens to be a URL) would be more harmful than substituting a
# generic placeholder.
sanitize_display_name = partial(
    _sanitize,
    validator=cast(_Validator, validate_display_name),
    log_event="email_utils.display_name_sanitized",
)

# Message-body fallback. Defaults `fallback` to an empty string so the optional message block
# in templates collapses cleanly when an inviter's free-text message fails validation.
sanitize_message_body = partial(
    _sanitize,
    validator=cast(_Validator, validate_message_body),
    log_event="email_utils.message_body_sanitized",
    fallback="",
)


# Zero-width space inserted after `.` and `:` to break auto-link patterns.
# We previously used `&#46;` / `&#58;` HTML entities, but Customer.io's
# template engine (TinyMCE-backed) decodes them on output, defeating the
# defang. ZWSP is a real Unicode codepoint, so it survives JSON transit and
# the ESP's template rendering. It's invisible to the recipient, but breaks
# the `\w+\.\w+` and `[a-z]+://` patterns mail-client auto-linkers scan for.
_ZWSP = "​"


def _defang_match(match: "re.Match[str]") -> str:
    return match.group(0).replace(".", f".{_ZWSP}").replace(":", f":{_ZWSP}")


def sanitize_email_string(value: str) -> str:
    """
    Sanitize a string for inclusion in email content (Customer.io
    `message_data` properties or Django email templates). Steps:

    1. NFKC-normalize so fullwidth / compatibility forms can't bypass the
       URL regexes (e.g. `ｈｔｔｐ：／／` → `http://`).
    2. Strip zero-width / direction-override / line-separator characters that
       could hide URL structure (`evil​.com` → `evil.com`). This runs *before*
       step 4 reintroduces zero-width spaces, so attacker-supplied invisibles
       can't survive but our defang ones can.
    3. HTML-escape so any embedded markup renders as text in the final email.
    4. Defang URL-shaped substrings: insert a zero-width space after each `.`
       and `:` inside a URL scheme (`https://`, `javascript:`, `www.`, ...) or
       a bare domain (`evil.com`) so mail clients do not auto-link them.

    Step 4 breaks the contiguous `\\w+\\.\\w+` / `[a-z]+://` patterns that
    mail-client auto-linkers scan for. The recipient still reads `evil.com`
    (the ZWSP is invisible) but the link is no longer clickable.
    """
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = _INVISIBLE_CHAR_RE.sub("", normalized)
    escaped = html.escape(cleaned)
    # No `.` or `:` means neither regex can match — skip the two passes.
    if "." not in escaped and ":" not in escaped:
        return escaped
    defanged = _URL_SCHEME_RE.sub(_defang_match, escaped)
    return _BARE_DOMAIN_RE.sub(_defang_match, defanged)


_ASCII_UPPER_TO_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


class EmailNormalizer:
    @staticmethod
    def normalize(email: str) -> str:
        """Fold an address into the form `User.email` stores.

        Only `A-Z` folds. Every lookup resolves an address through Postgres `LOWER`, and `A-Z` is
        the range where Python and Postgres agree. `str.lower()` maps `İ` (U+0130) to `i` plus a
        combining dot, where Postgres maps it to a plain `i`, so folding it here would store an
        address that no string a person can type folds onto. Postgres still folds the untouched
        characters at lookup time, so an address stays resolvable from any case it is typed in.
        """
        if not email:
            return email

        return email.translate(_ASCII_UPPER_TO_LOWER)


def email_domain(email: str) -> str | None:
    """The domain of `email`, or None when it carries no domain.

    The domain follows the last `@`. A local part may hold an `@` of its own inside a quoted
    string, which Django's `EmailValidator` accepts, so reading from the first `@` returns part of
    the local part and then matches no configured domain.
    """
    _, separator, domain = email.rpartition("@")
    if not separator or not domain:
        return None
    return domain


def strip_email_alias(email: str) -> str:
    """
    Strip a Gmail-style '+suffix' from the local part of an email (e.g.
    'someuser+alias@domain.com' -> 'someuser@domain.com'). Comparison-only —
    never use this for the email that actually gets stored.
    """
    if not email:
        return email
    local, _, domain = email.rpartition("@")
    local = local.split("+", 1)[0]
    return f"{local}@{domain}"


def _stripped_email(expression: "str | Value") -> Func:
    return Func(Lower(expression), Value(r"\+[^@]*@"), Value("@"), function="regexp_replace")


# SQL counterpart of `strip_email_alias`, lowercased. Shared by the lookup in
# `EmailValidationHelper.user_exists_with_stripped_alias` and by the `user_stripped_alias_idx`
# index on `User` that makes it an index lookup — Postgres only uses a functional index when
# the query filters on the identical expression, so these must not drift apart.
STRIPPED_EMAIL_EXPRESSION = _stripped_email("email")

GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def gmail_canonical_local_part(email: str) -> str | None:
    local, _, domain = strip_email_alias(EmailNormalizer.normalize(email)).rpartition("@")
    if domain not in GMAIL_DOMAINS:
        return None
    return local.replace(".", "")


GMAIL_CANONICAL_LOCAL_EXPRESSION = Replace(
    Func(STRIPPED_EMAIL_EXPRESSION, Value("@"), Value(1), function="split_part", output_field=CharField()),
    Value("."),
    Value(""),
)


def reject_plus_addressed_email(value: str) -> None:
    """Raise if the local part of `value` contains '+'."""
    local = value.rsplit("@", 1)[0]
    if "+" in local:
        raise serializers.ValidationError(
            "Email addresses with a '+' aren't supported. Please use your primary email address.",
            code="plus_addressing_not_allowed",
        )


# Mail systems fold these dots to "." or drop the hidden characters, so the address that reaches the
# mail provider is not the one we stored, and it can't receive verification or reset emails.
# Letters from any script stay allowed: only dot look-alikes and invisible formatting characters are here.
_LOOKALIKE_EMAIL_CHAR_RE = re.compile(
    r"[\u2024\u3002\ufe52\uff0e\uff61\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)


def reject_lookalike_email_characters(value: str) -> None:
    """Raise if `value` contains a look-alike dot or a zero-width character."""
    if _LOOKALIKE_EMAIL_CHAR_RE.search(value):
        raise serializers.ValidationError(
            "Enter an email address using standard dots and no hidden characters.",
            code="lookalike_characters_not_allowed",
        )


class EmailLookupHandler:
    @staticmethod
    def users_matching_email(email: str, queryset: Optional[QuerySet] = None) -> QuerySet:
        """
        Return the users whose address matches `email` under the fold that email lookups share.

        The fold is `LOWER`. `iexact` would fold on `UPPER`, which maps `ı` (U+0131) to `I` and `ſ`
        (U+017F) to `S`, while `LOWER` leaves both alone; `LOWER` in turn maps `İ` (U+0130) to `i`.
        Every case fold merges some characters, so what matters is that one fold is used everywhere.

        Postgres folds both sides. Python's `str.lower()` is a different operation: it maps `İ` to
        `i` plus a combining dot, where Postgres maps it to a plain `i`, so comparing a Postgres fold
        against a Python fold stops the owner of such an address matching their own row.

        A duplicate check on a path that writes `User.email` must use this fold. If it folds
        differently, an account can store an address that this lookup then resolves to another
        account, and that account's login and password reset reach the wrong row.
        """
        from posthog.models.user import User

        base = queryset if queryset is not None else User.objects.all()
        return base.alias(_lower_email=Lower("email")).filter(_lower_email=Lower(Value(email)))

    @staticmethod
    def get_user_by_email(email: str, is_active: Optional[bool] = True) -> Optional["User"]:
        """
        Resolve an email address to a user, case-insensitively.

        Accounts created before signup lowercased emails can differ from a newer account only by
        letter case. One case-insensitive rule keeps every caller on the same account, so a login,
        a password reset, and the login precheck cannot disagree about who is signing in.
        `EmailMultiRecordHandler` chooses between case variations when more than one matches, and
        `users_matching_email` holds the fold itself.
        """
        from posthog.models.user import User

        queryset = User.objects.filter(is_active=is_active) if is_active else User.objects.all()
        matches = EmailLookupHandler.users_matching_email(email, queryset)

        try:
            return matches.get()
        except User.DoesNotExist:
            return None
        except MultipleObjectsReturned:
            return EmailMultiRecordHandler.handle_multiple_users(matches, email, "user_lookup")


class EmailMultiRecordHandler:
    """
    Utility class for handling cases where multiple records exist with case variations of the same email.
    Provides deterministic behavior and comprehensive logging for monitoring and cleanup.
    """

    @staticmethod
    def handle_multiple_users(queryset: QuerySet, email: str, context: str) -> Optional["User"]:
        """
        Handle multiple user records with case variations of the same email.

        Returns:
            Last logged in user deterministically, preferring an active account
        """
        # An active account wins first. Login reads deactivated rows too, and Django rejects the
        # one row it gets back when that row is inactive, so a deactivated twin that won here would
        # lock the active owner out.
        # Postgres sorts NULLs first on a DESC order, so an account that never logged in would win
        # the tie-break. The account a person still uses is the one that logged in most recently.
        # `-pk` keeps the choice stable when no candidate has ever logged in, so every caller that
        # resolves this address agrees on one account.
        case_insensitive_matches = queryset.order_by(
            F("is_active").desc(), F("last_login").desc(nulls_last=True), "-pk"
        )
        user_count = case_insensitive_matches.count()
        last_logged_in_user = case_insensitive_matches.first()

        if user_count > 1:
            email_variations = list(case_insensitive_matches.values_list("email", flat=True))
            last_logged_in_user_id = last_logged_in_user.id if last_logged_in_user else None

            posthoganalytics.capture(
                "multiple users with email case variations",
                properties={
                    "email": email,
                    "user_count": user_count,
                    "email_variations": email_variations,
                    "last_logged_in_user_id": last_logged_in_user_id,
                },
            )

            logger.warning(
                f"Multiple users with case variations of email '{email}' during {context}. "
                f"Found {user_count} variations: {email_variations}. "
                f"Returning last logged in user (ID: {last_logged_in_user_id})"
            )

        return last_logged_in_user


class EmailValidationHelper:
    @staticmethod
    def user_exists(email: str) -> bool:
        return EmailLookupHandler.get_user_by_email(email) is not None

    @staticmethod
    def user_exists_with_stripped_alias(email: str, exclude_user_id: Optional[int] = None) -> bool:
        """
        True if any existing active user's email, once its '+alias' is stripped, equals `email`.
        `exclude_user_id` skips one account, so a user dropping their own '+alias' isn't blocked by themselves.
        """
        from posthog.models.user import User

        # Postgres folds and strips `email` with the same expression as the column, so this check
        # treats as taken every address that `EmailLookupHandler.users_matching_email` resolves.
        candidates = (
            User.objects.filter(is_active=True)
            .annotate(stripped_email=STRIPPED_EMAIL_EXPRESSION)
            .filter(stripped_email=_stripped_email(Value(email)))
        )
        if exclude_user_id is not None:
            candidates = candidates.exclude(pk=exclude_user_id)
        return candidates.exists()

    @staticmethod
    def user_exists_with_gmail_canonical(email: str, exclude_user_id: Optional[int] = None) -> bool:
        from posthog.models.user import User

        canonical_local = gmail_canonical_local_part(email)
        if canonical_local is None:
            return False
        gmail_domains = Q()
        for domain in GMAIL_DOMAINS:
            gmail_domains |= Q(email__iendswith=f"@{domain}")
        candidates = (
            User.objects.filter(gmail_domains, is_active=True)
            .annotate(gmail_canonical_local=GMAIL_CANONICAL_LOCAL_EXPRESSION)
            .filter(gmail_canonical_local=canonical_local)
        )
        if exclude_user_id is not None:
            candidates = candidates.exclude(pk=exclude_user_id)
        return candidates.exists()
