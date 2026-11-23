"""An OAuth app's scope ceiling, and how a requested scope list resolves against it."""

from collections.abc import Iterable, Sequence

from . import catalog, checks, exposure, oauth


def filter_to_unprivileged_scopes(scopes: Iterable[object]) -> list[str]:
    """Keep only self-serve-grantable scopes from a declared list, deduped, order preserved.

    The single allow-list for scopes a self-registering client declares, covering both DCR
    (the RFC 7591 `scope` string, split before it gets here) and CIMD (`com.posthog.scopes`).
    `UNPRIVILEGED_SCOPES` drops privileged (`llm_gateway:*`), internal, hidden, and unknown
    strings: none may reach a per-app ceiling, since `/authorize` would otherwise grant them
    on a user-consented token. Non-string entries are dropped too, so raw partner JSON is safe
    to pass straight in.
    """
    # Translated first, so metadata that still declares a renamed scope keeps it.
    declared = catalog.translate_renamed_scopes(token for token in scopes if isinstance(token, str))
    return [token for token in declared if token in exposure.UNPRIVILEGED_SCOPES]


def filter_self_registered_ceiling(scopes: Iterable[object]) -> list[str]:
    """The scope ceiling a self-registering client (DCR or CIMD) gets from the scopes it declares.

    Resource scopes go through `filter_to_unprivileged_scopes`. The OIDC identity scopes are
    granted on top of every ceiling, so a list that also names resource scopes drops them. A list
    of only identity scopes is a sign-in-only client and keeps them as its ceiling: a non-empty
    ceiling is an exhaustive allow-list, so the client can't get any resource scope. Dropping them
    would leave the ceiling empty, which callers reject or widen to the `UNPRIVILEGED_SCOPES` default.

    Returns `[]` only when nothing in `scopes` is grantable.
    """
    declared = list(scopes)
    resource_scopes = filter_to_unprivileged_scopes(declared)
    if resource_scopes:
        return resource_scopes
    return list(dict.fromkeys(token for token in declared if isinstance(token, str) and token in oauth.OIDC_SCOPES))


# Sentinel element in `OAuthApplication.scopes` meaning "the `UNPRIVILEGED_SCOPES`
# default *plus* the other listed scopes" — lets an app ride the broad default and add
# a few explicit (e.g. privileged) extras without enumerating the whole set, and keeps
# auto-tracking unprivileged scopes added later. Starts with `@` so it can never collide
# with a real `obj:action` scope. Not grantable itself: it's stripped from the resolved
# ceiling, and `filter_to_unprivileged_scopes` drops it so a self-registering app can't
# inject it to widen its own ceiling.
DEFAULT_CEILING_SENTINEL = "@default"


def resolve_ceiling(app_scopes: Iterable[str]) -> frozenset[str] | None:
    """An app's explicit scope ceiling, or `None` when it has none (empty `scopes`,
    which falls back to the `UNPRIVILEGED_SCOPES` default). A `@default` sentinel
    expands to `UNPRIVILEGED_SCOPES` unioned with the other listed scopes; without it,
    a non-empty ceiling stays an exhaustive allow-list. Entries are stripped so a
    fat-fingered `" @default"` still resolves (real scopes never have whitespace).

    This is the literal ceiling, which is also what a token carries on the paths that
    mint the whole thing (`create_wizard_oauth_access_token_for_user`, provisioning
    account requests). Read halves are added by `grantable_ceiling` at admission time
    instead, so testing a request against the ceiling can't quietly widen those."""
    app = {s.strip() for s in (app_scopes or [])}
    app.discard("")
    if not app:
        return None
    if DEFAULT_CEILING_SENTINEL in app:
        return frozenset(exposure.UNPRIVILEGED_SCOPES | (app - {DEFAULT_CEILING_SENTINEL}))
    return frozenset(app)


def effective_ceiling(app_scopes: Iterable[str]) -> frozenset[str]:
    """The scope set a request resolves against: the explicit `app_scopes` ceiling,
    or the broad `UNPRIVILEGED_SCOPES` default when the app has none."""
    ceiling = resolve_ceiling(app_scopes)
    return ceiling if ceiling is not None else exposure.UNPRIVILEGED_SCOPES


def grantable_ceiling(app_scopes: Iterable[str]) -> frozenset[str]:
    """The scopes a request may name: `effective_ceiling` plus the read half of every
    `<object>:write` entry.

    `APIScopePermission` already accepts a `:write` token wherever `:read` is required,
    so refusing a request for the narrower half denies access the token would have
    carried anyway. That is what the consent screen's read-only toggle asks for.

    Distinct from `effective_ceiling` because the read halves must not reach the paths
    that mint the whole ceiling as a token: widening those would hand partners and the
    wizard scope strings they never asked for, for no extra capability."""
    return checks._with_read_halves(effective_ceiling(app_scopes))


def scopes_within_ceiling(
    requested: Iterable[str],
    app_scopes: Iterable[str],
    *,
    allow_wildcard_under_empty_ceiling: bool = False,
) -> bool:
    """Whether every requested scope is grantable under an app's scope ceiling.

    The ceiling-resolution rule for callers that reject rather than clamp: the
    hand-rolled agentic-provisioning mint paths. `/authorize` resolves the same
    ceiling through `clamp_scopes_to_ceiling` instead, dropping ungrantable scopes
    rather than failing the request.

    - OIDC + introspection (`ALWAYS_ALLOWED_SCOPES`) are always granted.
    - An explicit `app_scopes` ceiling is an exhaustive allow-list: anything
      outside it is rejected, including `*`.
    - A `@default` sentinel in `app_scopes` resolves to `UNPRIVILEGED_SCOPES` plus
      the other listed scopes (see `resolve_ceiling`).
    - An empty `app_scopes` falls back to the broad `UNPRIVILEGED_SCOPES` default.

    `allow_wildcard_under_empty_ceiling` is the only resolution difference between
    the callers: `/authorize` passes `True` to grandfather legacy `*` clients (the
    PostHog Desktop CLI) until wildcard retirement, but not for self-registered (DCR
    or CIMD) clients, which were never part of that; provisioning leaves it `False`
    (the default) since it never granted wildcard, so an unseeded ceiling must not
    silently become one.
    """
    ceiling = resolve_ceiling(app_scopes)
    to_check = set(requested) - oauth.ALWAYS_ALLOWED_SCOPES
    if not to_check:
        return True
    if ceiling is not None:
        return "*" not in to_check and to_check.issubset(checks._with_read_halves(ceiling))
    allowed = (
        exposure.UNPRIVILEGED_SCOPES | {"*"} if allow_wildcard_under_empty_ceiling else exposure.UNPRIVILEGED_SCOPES
    )
    return to_check.issubset(allowed)


def scopes_outside_ceiling(
    requested: Iterable[str],
    app_scopes: Iterable[str],
    *,
    allow_wildcard_under_empty_ceiling: bool = False,
) -> list[str]:
    """The requested scopes that fall outside an app's ceiling — the inverse of
    `scopes_within_ceiling`, naming *which* scopes triggered an `invalid_scope`
    rejection rather than just whether one did. For instrumentation only; the
    resolution rules mirror `scopes_within_ceiling` exactly so the two never drift.

    Returns a sorted list, empty when every requested scope is grantable.
    """
    ceiling = resolve_ceiling(app_scopes)
    to_check = set(requested) - oauth.ALWAYS_ALLOWED_SCOPES
    if not to_check:
        return []
    if ceiling is not None:
        # `*` is never grantable under an explicit ceiling, even if listed.
        admissible = checks._with_read_halves(ceiling)
        return sorted(s for s in to_check if s == "*" or s not in admissible)
    allowed = (
        exposure.UNPRIVILEGED_SCOPES | {"*"} if allow_wildcard_under_empty_ceiling else exposure.UNPRIVILEGED_SCOPES
    )
    return sorted(to_check - allowed)


def clamp_scopes_to_ceiling(
    requested: Iterable[str],
    app_scopes: Iterable[str],
    *,
    allow_wildcard_under_empty_ceiling: bool = False,
) -> list[str]:
    """The grantable subset of a `/authorize` scope request.

    Where `scopes_within_ceiling` answers whether the whole request is grantable,
    this resolves it to what the token should actually carry. An ungrantable scope
    is dropped, never fatal: `/authorize` does not reject on scope grounds at all.
    Scopes are retired and renamed as a matter of routine, and a client pinning a
    hardcoded list has no way to see that coming. The resource metadata's
    `scopes_supported` is resource-wide, so a client cannot discover a narrower
    per-app ceiling before it asks either. RFC 6749 section 3.3 lets the server
    fully or partially ignore the requested scope as long as the token response
    reports what was granted, which oauthlib does whenever it differs.

    An empty return is a real outcome, not an error: the client asked for nothing
    grantable and gets an identity-only token. That client will 403 on every
    resource call, so `oauth_scopes_clamped` is the signal that matters here.

    Clamping can only ever grant less than the ceiling already allowed, so the
    ceiling stays the sole authority on what a token may hold. Resolution mirrors
    `scopes_within_ceiling` exactly:

    - `ALWAYS_ALLOWED_SCOPES` (OIDC + introspection) pass through untouched.
    - Under an explicit ceiling, `*` resolves to the whole ceiling rather than
      staying a wildcard, which is strictly less than the bypass `*` grants in
      `posthog/permissions.py`.
    - Under an empty ceiling, `*` is kept verbatim when the caller grandfathers it,
      because narrowing it there would strip the legacy client's full access.
      Otherwise it resolves to the `UNPRIVILEGED_SCOPES` default, as it resolves to
      an explicit ceiling. A verbatim `*` passes every non-internal scope check, so
      it would also carry the privileged and hidden scopes that the default excludes.
    """
    always_allowed = set(requested) & oauth.ALWAYS_ALLOWED_SCOPES
    resource_requested = set(requested) - oauth.ALWAYS_ALLOWED_SCOPES
    if not resource_requested:
        return sorted(always_allowed)

    ceiling = resolve_ceiling(app_scopes)
    if ceiling is not None:
        granted = (
            (ceiling - {"*"}) if "*" in resource_requested else (resource_requested & checks._with_read_halves(ceiling))
        )
    elif allow_wildcard_under_empty_ceiling:
        granted = resource_requested & (exposure.UNPRIVILEGED_SCOPES | {"*"})
    elif "*" in resource_requested:
        granted = set(exposure.UNPRIVILEGED_SCOPES)
    else:
        granted = resource_requested & exposure.UNPRIVILEGED_SCOPES

    return sorted(granted | always_allowed)


# How many real scopes a request has to carry before its trailing fragment reads as a cut
# URL rather than as a junk token. A false positive costs the app's whole ceiling, while a
# missed one only costs a short consent list, so the bar sits well above the length any
# deliberate request reaches by accident.
MIN_SCOPES_BEFORE_TRUNCATION = 20


def is_truncated_scope_request(requested: Sequence[str]) -> bool:
    """Whether a `scope` list looks cut off mid-token rather than merely stale.

    A client pinning a retired or renamed scope is routine, and `clamp_scopes_to_ceiling`
    drops those one at a time. A cut-off request is a different failure: something in the
    path truncated the authorization URL, so the last token is a fragment and every scope
    after it is gone, with no way to tell how many. Dropping the fragment the same way
    hands the user a short consent list and a half-working client, with no error anywhere.

    The signal is a final token that is a strict prefix of a real scope, with every token
    before it a real scope. A fragment can only ever be last, because the cut takes the
    rest of the string with it, and requiring a clean head keeps a client with one stale
    scope from reading as truncated. `requested` must preserve request order.

    The head also has to be long: `MIN_SCOPES_BEFORE_TRUNCATION` real scopes have to come
    through before a trailing fragment counts. Scope names are short common words, so a
    two-token request like `openid insight` prefixes a real scope by coincidence, and
    reading that as truncation hands the caller the app's whole ceiling. A URL that was
    actually cut carries most of the list before the cut, so the length is what separates
    the two.
    """
    if len(requested) <= MIN_SCOPES_BEFORE_TRUNCATION:
        return False

    *head, tail = requested
    known = exposure.ALL_SCOPES | oauth.ALWAYS_ALLOWED_SCOPES | {"*"}
    if not tail or tail in known or not all(scope in known for scope in head):
        return False

    return any(scope.startswith(tail) for scope in known)


def resolve_requested_scopes(
    requested: Sequence[str],
    app_scopes: Iterable[str],
    *,
    allow_wildcard_under_empty_ceiling: bool = False,
) -> list[str]:
    """The scopes an OAuth request gets: no scope, or a list cut off mid-token, resolves to the
    whole ceiling, and anything else is clamped to it.

    `/oauth/authorize` and `/oauth/device-authorization` both resolve scopes here, so a client
    gets the same scopes from either.
    """
    if not requested or is_truncated_scope_request(requested):
        return sorted(effective_ceiling(app_scopes) | oauth.ALWAYS_ALLOWED_SCOPES)
    return clamp_scopes_to_ceiling(
        set(requested), app_scopes, allow_wildcard_under_empty_ceiling=allow_wildcard_under_empty_ceiling
    )


def narrow_scopes_to_ceiling(original: Iterable[str], app_scopes: Iterable[str]) -> list[str] | None:
    """Cap previously-granted scopes at an app's current ceiling (refresh-time).

    Mirrors `OAuthValidator.get_original_scopes` so hand-rolled refresh flows
    drop scopes that were valid when issued but fall outside a since-tightened
    ceiling, rather than refreshing the broader set forever.

    - Empty `app_scopes` (no cap) returns `original` as a list, with renamed scopes translated.
    - A `*` token is left untouched (narrowing it would strip all resource
      access; `*` retirement is handled separately).
    - Otherwise returns the sorted intersection with the ceiling plus any
      always-allowed scopes, or `None` when a non-empty scope set narrows to
      nothing (the caller should reject with `invalid_grant` and force
      re-authorization, which can then grant whatever is inside the ceiling).

    A token that never held any scope is not that case, and rejecting it would
    loop: `/authorize` clamps rather than rejecting, so the re-authorization the
    rejection forces returns the same empty grant, which refreshes and is
    rejected again. It narrows to the empty list instead, leaving one stable
    token whose resource calls 403 by scope.
    """
    original_list = catalog.translate_renamed_scopes(original)
    ceiling = resolve_ceiling(app_scopes)
    if ceiling is None:
        return original_list

    original_set = set(original_list)
    if "*" in original_set:
        return original_list

    # A `:write` in the ceiling covers its `:read`, as at issue time in `clamp_scopes_to_ceiling`.
    narrowed = (original_set & checks._with_read_halves(ceiling)) | (original_set & oauth.ALWAYS_ALLOWED_SCOPES)
    if not narrowed and original_set:
        return None
    return sorted(narrowed)
