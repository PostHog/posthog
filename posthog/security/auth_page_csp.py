"""The Content-Security-Policy for the pages that take credentials or grant access.

Login, signup, password reset and email verification serve anonymous visitors, so the
per-person `csp-enforce-app-policy` flag has nobody to bucket there. The OAuth consent and
toolbar authorization pages serve signed-in visitors, but they grant access to the account,
so they take the same policy.
"""

import secrets
from typing import Literal, Optional, cast, get_args
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest

import structlog
import posthoganalytics

from posthog.constants import POSTHOG_JS_CLOUD_HOST, POSTHOG_JS_CLOUD_TOKEN
from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

AuthPageRoute = Literal["login", "signup", "reset", "verify_email", "oauth", "toolbar_oauth"]
AUTH_PAGE_ROUTES: frozenset[str] = frozenset(get_args(AuthPageRoute))

CSP_AUTH_PAGES_FLAG = "csp-auth-pages-policy"
# The flag releases to everyone and carries the rollout in its payload. Local evaluation matches
# this fixed id against that release, because these visitors have no person to bucket.
_FLAG_DISTINCT_ID = "csp-auth-pages"

DEFAULT_REPORT_SAMPLE_RATE = 0.1

_ANY_VISITOR_ROUTES: tuple[tuple[AuthPageRoute, str], ...] = (
    ("oauth", "/oauth/authorize"),
    ("toolbar_oauth", "/toolbar_oauth"),
)
# A signed-in visitor on these routes keeps the app policy. The SPA sends a signed-in visitor on
# from these screens to the app inside the same document, and the app loads from origins this
# policy refuses.
_ANONYMOUS_ROUTES: tuple[tuple[AuthPageRoute, str], ...] = (
    ("login", "/login"),
    ("signup", "/signup"),
    ("reset", "/reset"),
    ("reset", "/reset_2fa"),
    ("verify_email", "/verify_email"),
)


def _is_under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def auth_page_route(path: str, *, is_authenticated: bool) -> Optional[AuthPageRoute]:
    for route, prefix in _ANY_VISITOR_ROUTES:
        if _is_under(path, prefix):
            return route
    if is_authenticated:
        return None
    for route, prefix in _ANONYMOUS_ROUTES:
        if _is_under(path, prefix):
            return route
    return None


@frozen
class AuthPageRollout:
    enforce_percent: dict[str, int]
    # Per route, because traffic differs by orders of magnitude: reporting every violation costs
    # little on a route that sees a few documents a day, and floods ingestion on login.
    report_sample_rate: dict[str, float]


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def parse_rollout(payload: object) -> AuthPageRollout:
    """Read the payload field by field, so a typo in one route cannot enforce another.

    A missing or malformed value leaves its route report-only and the sample rate at the default.
    """
    if not isinstance(payload, dict):
        payload = {}
    enforce_percent: dict[str, int] = {}
    raw_enforce = payload.get("enforce")
    if isinstance(raw_enforce, dict):
        for route, percent in raw_enforce.items():
            if route in AUTH_PAGE_ROUTES and _is_number(percent):
                enforce_percent[route] = min(max(int(percent), 0), 100)
    report_sample_rate: dict[str, float] = {}
    raw_rates = payload.get("report_sample_rate")
    if isinstance(raw_rates, dict):
        for route, rate in raw_rates.items():
            if route in AUTH_PAGE_ROUTES and _is_number(rate) and 0 <= rate <= 1:
                report_sample_rate[route] = float(rate)
    return AuthPageRollout(enforce_percent=enforce_percent, report_sample_rate=report_sample_rate)


def _read_rollout() -> Optional[AuthPageRollout]:
    try:
        # Local evaluation only, as in csp_enforcement_enabled: a network call here would sit in
        # the path of every auth page.
        result = posthoganalytics.get_feature_flag_result(
            CSP_AUTH_PAGES_FLAG,
            _FLAG_DISTINCT_ID,
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        # A payload that is not JSON raises here too. Both cases fall back to the app policy.
        logger.warning("csp.auth_pages_flag_check_failed_defaulting_off", exc_info=True)
        return None
    if result is None or not result.enabled:
        return None
    return parse_rollout(result.payload)


@frozen
class AuthPageCsp:
    route: AuthPageRoute
    enforced: bool
    report_sample_rate: float


_UNDECIDED = object()


def auth_page_csp(request: HttpRequest) -> Optional[AuthPageCsp]:
    """The auth pages' policy for this document, or None when the document keeps the app policy.

    The template tells the frontend which policy it runs under, and CSPMiddleware builds the
    header, so the first call draws the enforcement bucket and later calls reuse it.
    CSPMiddleware runs before AuthenticationMiddleware, so the first call must come from the view
    or after it.
    """
    cache = vars(request)
    decision = cache.get("_auth_page_csp", _UNDECIDED)
    if decision is _UNDECIDED:
        decision = cache["_auth_page_csp"] = _decide(request)
    return cast(Optional[AuthPageCsp], decision)


def _decide(request: HttpRequest) -> Optional[AuthPageCsp]:
    user = getattr(request, "user", None)
    route = auth_page_route(request.path, is_authenticated=bool(user is not None and user.is_authenticated))
    if route is None:
        return None
    rollout = _read_rollout()
    if rollout is None:
        return None
    # Each document draws its own bucket. Nobody here has an identity to hold one, and a visitor
    # whose page breaks gets a fresh draw on reload, so a bad policy fails `percent` of attempts
    # rather than every attempt by an unlucky visitor. The cost is that a break can vanish on
    # reload, so reports, not user complaints, are the signal.
    enforced = secrets.randbelow(100) < rollout.enforce_percent.get(route, 0)
    return AuthPageCsp(
        route=route,
        enforced=enforced,
        report_sample_rate=rollout.report_sample_rate.get(route, DEFAULT_REPORT_SAMPLE_RATE),
    )


def static_asset_origin() -> str:
    """The one origin the frontend bundle, its stylesheet, fonts and images load from."""
    parts = urlsplit(settings.JS_URL)
    # An empty JS_URL means Django serves the bundle, which 'self' already covers.
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def posthog_js_host() -> str:
    """The host PostHog's own posthog-js sends to, or "" when it sends to this origin, as on a
    self-capturing install, which 'self' already covers. Mirrors the posthog-js context in
    posthog/utils.py."""
    return POSTHOG_JS_CLOUD_HOST if settings.E2E_TESTING or not settings.SELF_CAPTURE else ""


def _directive(name: str, *sources: str) -> str:
    return " ".join([name, *(source for source in sources if source)])


def build_auth_page_policy(
    *, nonce: str, static_origin: str, posthog_js_host: str, frame_ancestors: str, connect_debug_url: str
) -> list[str]:
    posthog_js_scripts = (
        [f"{posthog_js_host}/static/", f"{posthog_js_host}/array/{POSTHOG_JS_CLOUD_TOKEN}/config.js"]
        if posthog_js_host
        else []
    )
    return [
        # Firefox checks <link rel="modulepreload"> against default-src rather than script-src, so
        # without the static host it refuses the boot-chain preloads index.html emits. Every fetch
        # directive below sets its own sources, so nothing else falls back to this list.
        _directive("default-src", "'self'", static_origin),
        # 'strict-dynamic' trusts a script because a nonced script loaded it, and makes browsers
        # ignore every host source and 'self' in this directive. The app policy names every PostHog
        # host, so it is only as strong as every endpoint those hosts serve. Some serve code a
        # customer wrote, such as each project's remote config, which carries its site apps. That
        # config only registers functions and runs nothing on load, but this policy does not rest on
        # it: an injected <script src> carries no nonce, so it runs from no host at all.
        #
        # Everything these pages run arrives through a nonced script: the esbuild loader imports the
        # bundle, posthog-js injects its remote config and extensions, and the signup captcha
        # component injects Turnstile. Browsers that predate 'strict-dynamic' ignore that keyword
        # and fall back to the exact sources after it: the bundle host, the posthog-js extensions,
        # our own project's remote config and Turnstile.
        #
        # 'wasm-unsafe-eval' is here for the reason the app policy gives: the app shell warms
        # snappy-wasm when idle, anonymous pages included.
        _directive(
            "script-src",
            f"'nonce-{nonce}'",
            "'strict-dynamic'",
            "'wasm-unsafe-eval'",
            "'self'",
            static_origin,
            *posthog_js_scripts,
            "https://challenges.cloudflare.com",
        ),
        # 'unsafe-inline' stays because the page and its libraries add <style> elements without a
        # nonce: the boot styles in index.html, the country-flag font polyfill, custom theme CSS
        # and the Django error templates. A nonce here would make browsers ignore 'unsafe-inline'.
        #
        # Injected CSS can still read attribute values through selectors, so img-src and font-src
        # below name the bundle host rather than `https://*.posthog.com`. That wildcard includes
        # the ingestion hosts, which accept an event as a GET request under any project token, so
        # a selector could leak a value into a project the attacker reads.
        _directive("style-src", "'self'", "'unsafe-inline'", static_origin),
        _directive("font-src", "'self'", "data:", static_origin),
        # No `https:`: the app policy carries it for the OAuth application logo, a URL the
        # registrant supplies. OAuthConnectionLogos draws the app's initial instead of a
        # third-party logo on a document under this policy. The consent page shows the viewer's
        # avatar from Gravatar, which serves images only.
        _directive("img-src", "'self'", "data:", static_origin, "https://www.gravatar.com"),
        # Reaching these hosts needs script, which script-src already confines. posthog-js sends
        # to its own host, and snappy-wasm fetches its module from the bundle host.
        _directive("connect-src", "'self'", static_origin, posthog_js_host, connect_debug_url),
        # posthog-js builds its session recorder worker from a blob, as in the app policy.
        "worker-src 'self' blob:",
        # The signup captcha is the only frame these pages open.
        "frame-src https://challenges.cloudflare.com",
        "child-src 'none'",
        "object-src 'none'",
        "media-src 'none'",
        "manifest-src 'self'",
        "base-uri 'self'",
        # Every form on these pages submits over XHR, and every SSO and social login starts as a
        # link or a script navigation, so no form here posts through an identity provider. Google
        # is here for the reason the app policy gives: exiting impersonation posts to /logout,
        # which redirects through /admin/ to Google, and the consent page mounts that control.
        "form-action 'self' https://accounts.google.com",
        frame_ancestors,
    ]
