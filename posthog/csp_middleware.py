"""The Content Security Policy PostHog serves, and the middleware that attaches it.

The policy lives apart from the other middleware so that team-security owns the file in
`.github/CODEOWNERS` and reviews every change to it.
"""

import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit

from django.conf import settings
from django.http import HttpRequest

import structlog
import posthoganalytics

from posthog.cloud_utils import get_api_host, is_cloud
from posthog.constants import POSTHOG_JS_CLOUD_HOST, POSTHOG_JS_CLOUD_TOKEN
from posthog.models.utils import generate_random_token
from posthog.ph_client import PH_US_API_KEY, PH_US_HOST

logger = structlog.get_logger(__name__)


_POSTHOG_CSP_REPORT_ENDPOINT = f"{PH_US_HOST}/report/?token={PH_US_API_KEY}&v=2"


def csp_report_endpoint(**params: str) -> str:
    """The URL browsers report CSP violations and crashes to, or "" when reporting is turned off."""
    endpoint = settings.CSP_REPORT_ENDPOINT
    if endpoint is None:
        # Only deployments PostHog runs report to PostHog. Violations from an instance we do not
        # run tell us nothing we can act on, and reporting sends that instance's document URLs to a
        # destination its operator never chose. The gate is cloud rather than hobby because a
        # self-hosted install with DEBUG set runs in the local mode, not the hobby one.
        endpoint = _POSTHOG_CSP_REPORT_ENDPOINT if is_cloud() else ""
    if not endpoint or not params:
        return endpoint
    # The endpoint carries the destination's project token and report version, so a param the caller
    # passes replaces the one already there rather than repeating it.
    parts = urlsplit(endpoint)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return parts._replace(query=urlencode(query)).geturl()


# The full path, matched exactly. Django sends every unmatched path to the app catch-all, so a
# prefix match would also hand the app document this policy and stop it from starting.
REPLAY_PLAYER_FRAME_PATH = "/replay_player_frame/index.html"

# The app policy names only PostHog origins in `frame-ancestors`. Enforcing it on these paths stops
# every embedded dashboard, shared link and survey from rendering on a customer's site.
#
# The list follows `posthog/urls.py`. The Contour ingress keeps a similar list in
# `charts/argocd/contour-ingress/values/values.{dev,prod-us,prod-eu}.yaml`, which omits
# `/interview/` and the bare `/exporter`. Sync to the URL patterns, not to that list.
EMBEDDABLE_PATH_PREFIXES = (
    "/shared_dashboard/",
    "/shared/",
    "/embedded/",
    "/interview/",
    "/exporter/",
    "/external_surveys/",
)
EMBEDDABLE_PATHS = frozenset({"/render_query", "/exporter"})


def is_embeddable_document(path: str) -> bool:
    return path in EMBEDDABLE_PATHS or path.startswith(EMBEDDABLE_PATH_PREFIXES)


CSP_ENFORCE_APP_POLICY_FLAG = "csp-enforce-app-policy"
CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG = "csp-enforce-signed-out-pages"

# The pages that take a password or a one-time code. Other signed-out pages keep the report-only header.
SIGNED_OUT_ENFORCEABLE_PATH_PREFIXES = ("/login", "/signup", "/reset", "/reset_2fa", "/verify_email")


def is_signed_out_enforceable_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in SIGNED_OUT_ENFORCEABLE_PATH_PREFIXES)


def signed_out_csp_enforcement_enabled() -> bool:
    try:
        # A signed-out visitor has no person to bucket, so each document draws a random id. The
        # flag's rollout percentage then applies per document.
        #
        # A condition on a person property cannot resolve for a random id, so it evaluates to None
        # and enforces nothing. Flag events stay off, because each document would add a new
        # distinct id to the project.
        return bool(
            posthoganalytics.feature_enabled(
                CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG,
                str(uuid.uuid4()),
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("csp.signed_out_enforcement_flag_check_failed_defaulting_off", exc_info=True)
        return False


def csp_enforcement_enabled(request: HttpRequest) -> bool:
    user = getattr(request, "user", None)
    if user is None:
        return False
    if not user.is_authenticated:
        # The document keeps the policy it loads with. A visitor who signs in on login goes on to
        # the app inside the same document, so the draw here also covers that visit.
        return is_signed_out_enforceable_path(request.path) and signed_out_csp_enforcement_enabled()
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return False
    try:
        # Local evaluation only. A network call here would sit in the path of every HTML response,
        # and an unevaluable flag returns None, which leaves the policy report-only.
        #
        # Local evaluation holds the flag's conditions but not the person's properties, so a
        # condition on `email` cannot resolve unless the caller supplies it. Without this the
        # staff-only rollout every other flag here uses would return None and enforce nothing.
        return bool(
            posthoganalytics.feature_enabled(
                CSP_ENFORCE_APP_POLICY_FLAG,
                distinct_id,
                person_properties={"email": user.email} if user.email else {},
                only_evaluate_locally=True,
            )
        )
    except Exception:
        # A failed lookup and a deliberate opt-out both leave the policy report-only. The rollout
        # needs to tell them apart.
        logger.warning("csp.enforcement_flag_check_failed_defaulting_off", exc_info=True)
        return False


def app_csp_header_name(request: HttpRequest) -> str:
    if is_embeddable_document(request.path):
        return "Content-Security-Policy-Report-Only"
    if csp_enforcement_enabled(request):
        return "Content-Security-Policy"
    return "Content-Security-Policy-Report-Only"


# The app policy reports as v=2 through the endpoint above, and the shadow policy below as v=3.
NARROWED_APP_POLICY_REPORT_VERSION = "3"
_WILDCARD_SOURCES = frozenset({"https://*.posthog.com", "https://*.i.posthog.com"})


def narrowed_app_policy(csp_parts: list[str], replacements: dict[str, list[str]]) -> list[str]:
    """The app policy's directives named in `replacements`, with their wildcard hosts swapped for
    the sources given there.

    Sent report-only beside the app policy, it reports each load the wildcards admit and the named
    sources do not, which is the evidence for dropping the wildcards. worker-src comes along because
    workers fall back to script-src without it. The shadow names no other directive, so nothing else
    is restricted in it.
    """
    narrowed = []
    for part in csp_parts:
        name, *sources = part.split()
        if name in replacements:
            narrowed.append(" ".join([name, *(s for s in sources if s not in _WILDCARD_SOURCES), *replacements[name]]))
        elif name == "worker-src":
            narrowed.append(part)
    return narrowed


class CSPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        nonce = generate_random_token(16)
        request.csp_nonce = nonce

        # nonce must be added to request (above) before generating response
        response = self.get_response(request)

        content_type = response.get("Content-Type", "")
        # csp headers only matter on html documents, so for defense in depth, add strong csp to all other requests
        if "text/html" not in content_type:
            response.headers["Content-Security-Policy"] = "default-src 'none'"
            return response

        if request.path == REPLAY_PLAYER_FRAME_PATH:
            # rrweb's own iframe is on about:blank, and a frame on a local scheme inherits its
            # parent's policy wholesale. Mounting rrweb inside this document rather than the app's
            # makes this policy the one a recorded page is judged against.
            #
            # Recorded pages load whatever they loaded when recorded, so the media directives are
            # open on purpose. Scripts are the exception: rrweb sandboxes its frame without
            # allow-scripts, so nothing recorded ever executes, and 'none' states that rather than
            # leaving it to the sandbox attribute alone.
            #
            # No report-uri: violations here describe a customer's site, not ours.
            #
            # frame-ancestors stays open because shared and embedded recordings put the app itself
            # in a customer's page, which makes this frame's ancestor chain cross-origin. The
            # document holds no data and cannot be scripted into cross-origin, so framing it
            # elsewhere yields a blank page.
            response.headers["Content-Security-Policy"] = "; ".join(
                [
                    "default-src 'none'",
                    "script-src 'none'",
                    "style-src * 'unsafe-inline' data: blob:",
                    "img-src * data: blob:",
                    "font-src * data: blob:",
                    "media-src * data: blob:",
                    "connect-src *",
                    "frame-src *",
                    "child-src *",
                    "form-action 'none'",
                    "base-uri 'none'",
                    "frame-ancestors *",
                ]
            )
            return response

        # With the admin portal off, Django admin is not mounted and `/admin/` reaches the app catch-all.
        # Choosing the admin policy by path alone would then enforce it on the app, and it has no
        # connect-src, so the app's own analytics and feature flag requests are refused.
        is_admin_view = getattr(settings, "ADMIN_PORTAL_ENABLED", False) and request.path.startswith("/admin/")
        if is_admin_view:
            django_loginas_inline_script_hash = "sha256-2bSkJXtgXFhxZUhgXzWsEsKImxJEQsqjns0vi3KiSrI="
            csp_parts = [
                "default-src 'self'",
                "style-src 'self' 'unsafe-inline'",
                f"script-src 'self' 'nonce-{nonce}' '{django_loginas_inline_script_hash}'",
                "font-src data: https://fonts.gstatic.com",
                # Without this the directive falls back to `default-src 'self'`, which drops the
                # `data:` icons Django admin and our own admin pages render, and the `blob:` images
                # the admin tools build client-side. Neither can execute, and this policy is
                # enforced for every staff member rather than flag-gated, so the fallback was
                # breaking admin pages outright.
                "img-src 'self' data: blob:",
                "worker-src 'none'",
                "child-src 'none'",
                "object-src 'none'",
                "frame-ancestors 'none'",
                "manifest-src 'none'",
                # used by the error page
                "frame-src https://posthog.com",
                "base-uri 'self'",
            ]

            admin_report_endpoint = csp_report_endpoint()
            if admin_report_endpoint:
                # Without a distinct_id the report endpoint mints a new one for every report, so a
                # single staff session reads as a crowd of users.
                user = getattr(request, "user", None)
                distinct_id = getattr(user, "distinct_id", None) if user is not None and user.is_authenticated else None
                reporting_endpoint = (
                    csp_report_endpoint(distinct_id=distinct_id) if distinct_id else admin_report_endpoint
                )
                # The policy has no `report-to` directive. The app policy below gives the reason.
                csp_parts.append(f"report-uri {reporting_endpoint}")
                # Browsers only deliver crash reports to the endpoint named `default`.
                response.headers["Reporting-Endpoints"] = f'default="{reporting_endpoint}"'
            response.headers["Content-Security-Policy"] = "; ".join(csp_parts)
        elif "Content-Security-Policy" in response.headers:
            # The view picked this policy for this document: a canvas artifact runs untrusted code,
            # and the workflow asset endpoint sandboxes captured email HTML. The app policy would
            # drop that sandbox and impose a frame-ancestors list the app's own origin does not
            # match. Adding it report-only is no better, because these documents never aim to
            # satisfy it, so each load would report a violation of a policy we chose not to apply.
            return response
        else:
            resource_url = "https://*.posthog.com"
            # Enforced for every viewer, flag or not, because this directive is what admits these
            # origins: a frame-ancestors directive makes browsers ignore X-Frame-Options, which
            # names only our own origin.
            frame_ancestors = "frame-ancestors https://posthog.com https://preview.posthog.com"
            if settings.DEBUG or settings.TEST:
                resource_url = "http://localhost:8234"
            elif settings.SITE_URL.endswith(".dev.posthog.dev"):
                resource_url = "https://*.dev.posthog.dev"
                # The posthog.com dev server frames the dev app.
                frame_ancestors += " http://localhost:8001"

            connect_debug_url = "ws://localhost:8234" if settings.DEBUG or settings.TEST else ""
            js_url = urlsplit(settings.JS_URL)
            bundle_origin = f"{js_url.scheme}://{js_url.netloc}" if js_url.scheme and js_url.netloc else ""
            csp_parts = [
                # Firefox checks <link rel="modulepreload"> against default-src instead of script-src,
                # so without the bundle host it refuses the preloads index.html emits for the boot
                # chain. Every preload href starts with JS_URL, so its origin is the one host needed.
                # The fetch directives below each set their own sources, so only a load a browser
                # cannot map to one of them falls back to this list.
                f"default-src 'self' {bundle_origin}".rstrip(),
                f"style-src 'self' 'unsafe-inline' {resource_url} https://fonts.googleapis.com",
                # 'wasm-unsafe-eval' permits WebAssembly compilation and nothing else. It is not
                # 'unsafe-eval': it does not permit eval() or the Function constructor. Compiling a
                # module still requires calling WebAssembly.instantiate from JavaScript, so it grants
                # nothing to an attacker who cannot already run script, and nothing further to one who
                # can. Session replay decompresses snapshots with snappy-wasm and the HogQL editor
                # parses with a WebAssembly build, so both break without it.
                #
                # Stripe, Turnstile and Unlayer are the scripts we cannot serve ourselves: each vendor
                # requires the file to load from their own origin, so the flag-font trick of shipping
                # a copy does not apply. `loadStripe` injects js.stripe.com for the payment entry
                # modal, the signup captcha loads the Turnstile API, and `react-email-editor` injects
                # editor.unlayer.com/embed.js for the email templater. `frame-src 'self' https:`
                # already admits the iframes each one opens, and none produced a connect-src
                # violation while this policy was report-only, so their API calls run inside those
                # frames rather than from our page. Unlayer bears that out: embed.js is the only
                # unlayer URL this policy has ever reported, because the editor itself runs in a
                # frame that carries its own policy rather than ours.
                #
                # Unlayer is pinned to a path rather than the host, because react-email-editor
                # hardcodes that one URL and we do not pass its `scriptUrl` prop. A source path is
                # matched against the URL path alone, so the `?2` the library appends does not
                # defeat it. The cost is that a version bump which moves the file needs this line
                # updated, or the editor stops loading.
                f"script-src 'self' 'nonce-{nonce}' 'wasm-unsafe-eval' {resource_url} https://*.i.posthog.com https://js.stripe.com https://challenges.cloudflare.com https://editor.unlayer.com/embed.js",
                # A data: font cannot execute script, and this directive governs font loading only,
                # so the token widens nothing else. It also carries nothing out: a data: URL makes
                # no request, which is what the CSS-injection attacks on this directive need. The
                # `data:` refusal in the worker-src note below is a different case, because a
                # worker body is code.
                f"font-src 'self' data: {resource_url} https://app-static.eu.posthog.com https://app-static-prod.posthog.com https://fonts.gstatic.com",
                # `blob:` grants nothing to an attacker who cannot already run script, because only
                # script can mint a blob URL, and a worker started from one inherits this policy
                # rather than escaping it. The ServiceWorker spec rejects `blob:` on its own, so
                # this cannot register a persistent worker either.
                #
                # The reasoning holds only while every blob worker body is a compile-time constant.
                # `no-dynamic-worker-body` in .semgrep/rules/security checks first-party code for
                # that. It follows an object URL or a `data:` URL into a worker constructor through
                # the assignments in one function, so it catches the shapes we write rather than
                # every possible one.
                #
                # posthog-js builds its rrweb recorder worker from a blob, and PixiJS builds two
                # ImageBitmap workers the same way. Do not add `data:`: the recorder falls back to a
                # data URL only when blob fails, so allowing blob stops those attempts.
                "worker-src 'self' blob:",
                "child-src 'none'",
                "object-src 'none'",
                # `'self'` carries the PostHog AI onboarding videos under /static/. Max hands-free
                # needs the other two: it primes playback with a silent `data:` clip, then plays
                # the TTS response from a blob URL. None of the three can execute, because
                # media-src governs <audio> and <video> only.
                "media-src 'self' data: blob: https://res.cloudinary.com",
                # `https:` is here for the OAuth authorize page, which renders an application's icon
                # from a URL its registrant supplied. There is no allowlist that covers those, so
                # until we serve them ourselves the directive has to accept any host.
                #
                # The named origins below are the set we actually load images from, and `https:`
                # makes them redundant. They stay so that removing `https:` is a one-line change
                # rather than an archaeology exercise.
                #
                # Do not promote this to an enforced header as-is. An open `img-src` is an
                # exfiltration channel: an attacker who injects markup but cannot run script still
                # gets a beacon out through an image URL.
                # `blob:` is not part of that exfiltration surface: only script already running on
                # the page can mint a blob URL, and an image cannot execute, so it grants strictly
                # less than the `worker-src blob:` note below. Image upload previews, replay and the
                # SQL editor all render blob URLs, so they lose their images without it.
                f"img-src 'self' data: blob: https: {resource_url} https://posthog.com https://www.gravatar.com https://res.cloudinary.com https://platform.slack-edge.com https://raw.githubusercontent.com",
                frame_ancestors,
                # The live debugger's repo browser reads PostHog/posthog from the GitHub API. The path keeps
                # the rest of the API, and every other repository, out of reach of injected script.
                f"connect-src 'self' https://www.posthogstatus.com {resource_url} {connect_debug_url} https://api.github.com/repos/PostHog/posthog/ https://raw.githubusercontent.com/PostHog/terminal-assets/",
                # https: lets heatmaps frame a customer's site. 'self' is for the replay player
                # frame, whose document is same-origin: an http origin does not match https:.
                "frame-src 'self' https:",
                "manifest-src 'self'",
                "base-uri 'self'",
                # form-action has no default-src fallback, so leaving it unset lets an injected
                # form post anywhere. Every form we serve targets a same-origin path, but Chromium
                # judges each hop of the redirect chain too, and reports the original action rather
                # than the hop that failed. Exiting impersonation posts to /logout, which redirects
                # into /admin/, and AdminOAuth2Middleware sends that on to Google because
                # restore_original_login() flushes the session holding the admin verification. So
                # without this origin a staff logout is cancelled with nothing shown to the user.
                "form-action 'self' https://accounts.google.com",
            ]

            # Both values are read inside one narrowed block, so nothing below re-checks `user`.
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                is_staff = bool(getattr(user, "is_staff", False))
                distinct_id = getattr(user, "distinct_id", None)
            else:
                is_staff = False
                distinct_id = None

            # Staff get the policy enforced ahead of everyone else, so each violation they report is
            # something already broken for a colleague rather than one sample of a trend. At 0.1 we
            # would see one breakage in ten, which is the opposite of what the staff rollout is for.
            # The endpoint does the sampling, so browsers already send every report and taking staff
            # to 1 costs ingestion rather than client traffic.
            #
            # This keys on is_staff rather than on the enforcement flag, which would otherwise track
            # the enforced population exactly. The flag widens until it covers everyone, and would
            # silently take the whole fleet to unsampled reporting; staff stays bounded.
            sample_rate = "1" if is_staff else "0.1"

            report_uri = csp_report_endpoint(sample_rate=sample_rate)
            shadow_parts: list[str] = []
            if report_uri and is_cloud() and resource_url == "https://*.posthog.com" and not settings.E2E_TESTING:
                bundle = [bundle_origin] if bundle_origin else []
                agent_proxy_url = settings.TASKS_AGENT_PROXY_PUBLIC_URL
                agent_proxy = (
                    [urlsplit(agent_proxy_url)._replace(path="", query="", fragment="").geturl()]
                    if agent_proxy_url
                    else []
                )
                replacements = {
                    # posthog-js loads its extensions from /static/ and our project's remote config. The
                    # config path names our token because the same path serves every project's config.
                    "script-src": [
                        *bundle,
                        f"{POSTHOG_JS_CLOUD_HOST}/static/",
                        f"{POSTHOG_JS_CLOUD_HOST}/array/{POSTHOG_JS_CLOUD_TOKEN}/config.js",
                    ],
                    # liveEventsHostOrigin() in the frontend streams from live.<region host>.
                    "connect-src": [
                        *bundle,
                        POSTHOG_JS_CLOUD_HOST,
                        f"https://live.{urlsplit(settings.SITE_URL).hostname}",
                        # The onboarding adblock check probes the region's ingestion host.
                        f"{get_api_host()}/decide/",
                        # A task run's live stream, when the server hands out the region's agent-proxy.
                        *agent_proxy,
                    ],
                }
                shadow_uri = csp_report_endpoint(sample_rate=sample_rate, v=NARROWED_APP_POLICY_REPORT_VERSION)
                shadow_parts = [*narrowed_app_policy(csp_parts, replacements), f"report-uri {shadow_uri}"]
            if report_uri:
                report_endpoint = report_uri
                if distinct_id:
                    # A report body never names the person, and a crash report arrives after the tab
                    # already died, so only the URL can carry the distinct_id. Without it, the report
                    # endpoint mints a random id for every report.
                    report_endpoint = csp_report_endpoint(sample_rate=sample_rate, distinct_id=distinct_id)
                # The policy has no `report-to` directive, even though CSP3 marks `report-uri` as
                # deprecated. While a policy names `report-to`, browsers ignore its `report-uri` and
                # send reports only through the Reporting API. That API drops violations raised in
                # about:blank and srcdoc frames, because those documents inherit this policy but not
                # the Reporting-Endpoints header. Without `report-to`, browsers send those violations
                # to `report-uri`.
                csp_parts.append(f"report-uri {report_endpoint}")
                # Browsers only deliver crash reports to the endpoint named `default`.
                response.headers["Reporting-Endpoints"] = f'default="{report_endpoint}"'
            header_name = app_csp_header_name(request)
            response.headers[header_name] = "; ".join(csp_parts)
            if shadow_parts:
                # One header can carry several policies separated by commas, and the browser checks
                # each on its own.
                shadow = "; ".join(shadow_parts)
                reported = response.headers.get("Content-Security-Policy-Report-Only")
                response.headers["Content-Security-Policy-Report-Only"] = (
                    f"{reported}, {shadow}" if reported else shadow
                )
            if header_name == "Content-Security-Policy-Report-Only" and not is_embeddable_document(request.path):
                # Django owns this header. A responseHeadersPolicy on the Contour ingress replaces
                # it, and with it the enforced app policy above, so the ingress must not set one.
                response.headers["Content-Security-Policy"] = frame_ancestors

        return response
