from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from posthog.test.base import APIBaseTest, override_settings
from unittest.mock import MagicMock

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.csp_middleware import CSPMiddleware, app_csp_header_name, narrowed_app_policy, object_storage_upload_source


def _parse_policies(header: str) -> list[dict[str, list[str]]]:
    return [
        {name: sources for name, *sources in (part.split() for part in policy.split("; "))}
        for policy in header.split(", ")
        if policy
    ]


def _report_version(policy: dict[str, list[str]]) -> list[str] | None:
    return parse_qs(urlsplit(policy.get("report-uri", [""])[0]).query).get("v")


_US_BUNDLE = "https://app-static-prod.posthog.com"


class _PageLoads(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[tuple[dict[str, str | None], str]] = []
        self.stylesheets: list[str] = []
        self._script: dict[str, str | None] | None = None
        self._script_body = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._script, self._script_body = dict(attrs), ""
        elif tag == "link" and dict(attrs).get("rel") == "stylesheet":
            self.stylesheets.append(dict(attrs).get("href") or "")

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script_body += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.scripts.append((self._script, self._script_body.strip()))
            self._script = None


def _admits(sources: list[str], url: str) -> bool:
    parts = urlsplit(url)
    if not parts.netloc:
        return "'self'" in sources
    return f"{parts.scheme}://{parts.netloc}" in sources


# Tests run as a self-hosted install, which never enforces. LOCAL enforces without turning on DEBUG.
@override_settings(CLOUD_DEPLOYMENT="LOCAL")
class TestCSPMiddleware(APIBaseTest):
    def test_replay_player_frame_carries_its_own_policy_and_reports_nothing(self):
        # The frame exists so a recorded page stops being judged against the app policy. If the
        # middleware branch goes, it silently inherits that policy again, along with its report-uri,
        # and every replayed page resumes reporting a customer's site to our project.
        response = self.client.get("/replay_player_frame/index.html")
        assert response.status_code == 200
        policy = response["Content-Security-Policy"]
        assert "script-src 'none'" in policy
        assert "img-src * data: blob:" in policy
        assert "report-uri" not in policy
        assert "Content-Security-Policy-Report-Only" not in response
        assert "Reporting-Endpoints" not in response

    def test_app_policy_allows_framing_the_replay_player_frame(self):
        # The player frame is same-origin, and an http origin does not match the https: source
        # that heatmaps need.
        response = self.client.get("/")
        assert "frame-src 'self' https:" in response["Content-Security-Policy"]

    @parameterized.expand(
        [
            ("local", {}, "default-src 'self' http://localhost:8234;"),
            # The bundle host alone. The rest of the policy names every PostHog subdomain, and a
            # fallback that broad admits whatever a new directive forgets to restrict.
            (
                "cloud",
                {
                    "TEST": False,
                    "DEBUG": False,
                    "CLOUD_DEPLOYMENT": "US",
                    "SITE_URL": "https://us.posthog.com",
                    "JS_URL": "https://app-static-prod.posthog.com",
                },
                "default-src 'self' https://app-static-prod.posthog.com;",
            ),
        ]
    )
    def test_app_policy_lets_firefox_preload_the_app_bundle(self, _name, overrides, expected):
        # Firefox judges <link rel="modulepreload"> by default-src, not script-src. A default-src of
        # 'self' alone refuses every preload index.html emits for the boot chain.
        with override_settings(**overrides):
            response = self.client.get("/")
        assert expected in response["Content-Security-Policy"]

    def test_dev_policy_admits_a_remote_vite_host(self):
        # A devbox serves Vite from its Coder host, so a policy naming only localhost renders a blank page.
        with override_settings(JS_URL="https://frontend--devbox--jane.coder.example.com"):
            response = self.client.get("/")
        script_src = next(
            part for part in response["Content-Security-Policy"].split("; ") if part.startswith("script-src ")
        ).split()
        assert {"http://localhost:8234", "https://frontend--devbox--jane.coder.example.com"} <= set(script_src)

    @parameterized.expand(
        [
            ("opted_in", True, True),
            ("not_opted_in", False, False),
        ]
    )
    def test_dev_policy_admits_the_code_inspector_only_when_opted_in(self, _name, opted_in, expected):
        # The inspector server answers any origin, so the policy must not reach it unless the engineer asked for it.
        with override_settings(DEBUG=True, DEV_CODE_INSPECTOR=opted_in):
            response = self.client.get("/")
        connect_src = next(
            part for part in response["Content-Security-Policy"].split("; ") if part.startswith("connect-src ")
        ).split()
        assert ("http://localhost:5678" in connect_src) is expected

    def test_replay_player_frame_serves_the_mount_node_without_a_session(self):
        # Shared recordings render the player for logged-out viewers.
        self.client.logout()
        response = self.client.get("/replay_player_frame/index.html")
        assert response.status_code == 200
        # PlayerFrame.tsx looks the mount node up by this id. A rename here makes every player show its load error.
        assert 'id="player-frame-content"' in response.content.decode()

    def test_non_html_response_gets_strict_csp(self):
        response = self.client.get("/api/users/@me/")
        assert response.status_code == 200
        assert response["Content-Security-Policy"] == "default-src 'none'"
        assert "Content-Security-Policy-Report-Only" not in response

    @parameterized.expand([("swagger", "/api/schema/swagger-ui/"), ("redoc", "/api/schema/redoc/")])
    @override_settings(
        TEST=False,
        DEBUG=False,
        CLOUD_DEPLOYMENT="US",
        SITE_URL="https://us.posthog.com",
        JS_URL="https://app-static-prod.posthog.com",
    )
    def test_api_doc_pages_load_only_what_the_app_policy_admits(self, _name: str, path: str) -> None:
        # drf-spectacular defaults to a public CDN and to an inline init script with no nonce. The
        # enforced app policy refuses both, and the page renders blank with no error shown.
        response = self.client.get(path)
        assert response.status_code == 200
        policy = next(p for p in _parse_policies(response["Content-Security-Policy"]) if "script-src" in p)
        page = _PageLoads()
        page.feed(response.content.decode())

        assert page.scripts
        for attrs, body in page.scripts:
            src = attrs.get("src")
            if src is None:
                assert f"'nonce-{attrs.get('nonce')}'" in policy["script-src"], body[:80]
            else:
                assert _admits(policy["script-src"], src), src
                if not urlsplit(src).netloc and not src.startswith(settings.STATIC_URL):
                    # The Swagger init script comes from the page's own URL. A response that is not
                    # JavaScript leaves the page blank without any violation to report.
                    script = self.client.get(src)
                    assert script.status_code == 200, src
                    assert "javascript" in script["Content-Type"], src
        for href in page.stylesheets:
            assert _admits(policy["style-src"], href), href

    @parameterized.expand(
        [
            # No route serves this path, so the app catch-all answers it. It must keep the app
            # policy, because the frame policy is enforced and its script-src 'none' stops the app
            # from starting.
            ("path_under_the_replay_frame_prefix", "/replay_player_frame", 302),
            # The status proves the page renders for a signed-out visitor. A path that redirects to
            # /login only repeats the row above.
            ("page_that_needs_no_login", "/preflight", 200),
        ]
    )
    def test_signed_out_page_is_fully_enforced(self, _name: str, path: str, status: int) -> None:
        self.client.logout()
        response = self.client.get(path)
        assert response.status_code == status
        assert "default-src 'self'" in response["Content-Security-Policy"]
        assert "Content-Security-Policy-Report-Only" not in response

    def test_enforcement_reaches_app_and_shared_pages_but_not_the_exporter(self):
        # The wiring guard for app_csp_header_name. The matrix of paths lives in
        # TestAppCspHeaderName, which needs no database.
        enforced = self.client.get("/")
        assert "default-src 'self'" in enforced["Content-Security-Policy"]
        assert "Content-Security-Policy-Report-Only" not in enforced

        for path in ("/shared/notarealtoken", "/exporter/notarealtoken"):
            shared = self.client.get(path)
            assert "default-src 'self'" in shared["Content-Security-Policy"], path
            assert "frame-ancestors" not in shared["Content-Security-Policy"], path
            assert "Content-Security-Policy-Report-Only" not in shared, path

        exporter = self.client.get("/exporter")
        assert "Content-Security-Policy" not in exporter
        assert "frame-ancestors" not in exporter["Content-Security-Policy-Report-Only"]

    @override_settings(CLOUD_DEPLOYMENT=None, DEBUG=False)  # As a self-hosted install
    def test_self_hosted_install_enforces_only_frame_ancestors(self) -> None:
        response = self.client.get("/")
        enforced = response["Content-Security-Policy"]
        # The enforced list has to be the one the reported policy names, or the two drift apart.
        assert enforced.startswith("frame-ancestors 'self' https://posthog.com")
        assert "default-src" not in enforced
        assert enforced in response["Content-Security-Policy-Report-Only"]

    @override_settings(CLOUD_DEPLOYMENT="US")  # As PostHog Cloud
    def test_html_response_declares_default_reporting_endpoint_with_distinct_id(self):
        response = self.client.get("/")
        policy = response["Content-Security-Policy"]
        # A `report-to` directive makes browsers ignore `report-uri` and report through the
        # Reporting API, which drops violations raised in about:blank and srcdoc frames.
        assert "report-to" not in policy
        _, report_endpoint = next(part for part in policy.split("; ") if part.startswith("report-uri ")).split()
        assert report_endpoint.startswith("https://us.i.posthog.com/report/")
        assert f"distinct_id={self.user.distinct_id}" in report_endpoint
        # An enforced violation is a page that broke for someone, so dropping reports hides breakages.
        assert "sample_rate" not in report_endpoint
        # Browsers only deliver crash reports to the endpoint named `default`, so dropping or
        # renaming it silently stops crash ingestion.
        assert response["Reporting-Endpoints"] == f'default="{report_endpoint}"'

    @override_settings(CLOUD_DEPLOYMENT="US")  # As PostHog Cloud
    def test_reporting_endpoints_omit_distinct_id_when_logged_out(self):
        self.client.logout()
        response = self.client.get("/login")
        policy = response["Content-Security-Policy"]
        assert "report-uri https://us.i.posthog.com/report/" in policy
        assert "distinct_id" not in policy
        header = response["Reporting-Endpoints"]
        assert 'default="https://us.i.posthog.com/report/' in header
        assert "distinct_id" not in header

    @parameterized.expand(
        [
            # Nobody sees a self-hosted install's violations, so enforcing there would break pages silently.
            (
                "self_hosted_by_default",
                {"CLOUD_DEPLOYMENT": None, "DEBUG": False},
                "Content-Security-Policy-Report-Only",
            ),
            # DEBUG puts an install in the local run mode rather than the hobby one, and nothing
            # stops a self-hoster deploying that way, so it must report nowhere as well. Local
            # development enforces, so a change that breaks the policy shows up there first.
            ("self_hosted_with_debug", {"CLOUD_DEPLOYMENT": None, "DEBUG": True}, "Content-Security-Policy"),
            # Cloud would otherwise report, so this case proves the empty value turns it off.
            (
                "explicitly_disabled",
                {"CLOUD_DEPLOYMENT": "US", "CSP_REPORT_ENDPOINT": ""},
                "Content-Security-Policy",
            ),
        ]
    )
    def test_no_endpoint_still_sends_the_policy_but_asks_for_no_reports(self, _name, overrides, header):
        # A self-hosted install must not report to PostHog, and the policy itself must survive, so
        # dropping it here would silently remove a security control.
        with override_settings(**{"CSP_REPORT_ENDPOINT": None, **overrides}):
            response = self.client.get("/")
        policy = response[header]
        assert "default-src 'self'" in policy
        assert "report-uri" not in policy
        assert "report-to" not in policy
        assert "Reporting-Endpoints" not in response

    @override_settings(CSP_REPORT_ENDPOINT="https://posthog.example.com/report/")
    def test_report_endpoint_is_configurable(self):
        # An operator can point reporting at their own install, so nothing may hardcode ours.
        response = self.client.get("/")
        policy = response["Content-Security-Policy"]
        assert "report-uri https://posthog.example.com/report/" in policy
        header = response["Reporting-Endpoints"]
        assert "us.i.posthog.com" not in header
        assert f"distinct_id={self.user.distinct_id}" in header

    @parameterized.expand(
        [
            ("cloud", {"CLOUD_DEPLOYMENT": "US"}, True),
            ("self_hosted", {"CLOUD_DEPLOYMENT": None, "DEBUG": False}, False),
        ]
    )
    def test_admin_pages_enforce_the_policy_and_follow_the_reporting_default(self, _name, overrides, expects_reporting):
        # The admin policy is enforced, not report-only, and builds its own Reporting-Endpoints
        # header, so it can drift from the app policy unnoticed. A non-staff request redirects but
        # still carries that policy, because the middleware picks its branch by path once the portal is on.
        with override_settings(CSP_REPORT_ENDPOINT=None, ADMIN_PORTAL_ENABLED=True, **overrides):
            response = self.client.get("/admin/")
        policy = response["Content-Security-Policy"]
        # Only the admin policy forbids framing outright; the non-HTML fallback is default-src alone.
        assert "frame-ancestors 'none'" in policy
        assert "Content-Security-Policy-Report-Only" not in response
        assert "report-to" not in policy

        if expects_reporting:
            assert "report-uri https://us.i.posthog.com/report/" in policy
            # Sampling would silently drop violations.
            assert "sample_rate" not in policy
            # Without it every admin report arrives under a freshly minted id, so one staff session
            # counts as many users.
            assert f"distinct_id={self.user.distinct_id}" in policy
            _, report_endpoint = next(part for part in policy.split("; ") if part.startswith("report-uri ")).split()
            assert response["Reporting-Endpoints"] == f'default="{report_endpoint}"'
        else:
            assert "report-uri" not in policy
            assert "Reporting-Endpoints" not in response

    @override_settings(ADMIN_PORTAL_ENABLED=False)
    def test_admin_path_gets_the_app_policy_when_the_portal_is_off(self):
        # Without the portal, `/admin/` is an app page, and the app keeps running in that document
        # after it navigates away. The admin policy there would refuse every request the app makes
        # to another origin.
        response = self.client.get("/admin/")
        policy = response["Content-Security-Policy"]
        assert "frame-ancestors 'none'" not in policy
        assert "connect-src 'self'" in policy

    @parameterized.expand(
        [
            (
                "cloud_us",
                {
                    "CLOUD_DEPLOYMENT": "US",
                    "SITE_URL": "https://us.posthog.com",
                    "JS_URL": "https://app-static-prod.posthog.com",
                    "TASKS_AGENT_PROXY_PUBLIC_URL": "https://agent-proxy.us.posthog.com",
                },
                ("us", "eu"),
            ),
            (
                "cloud_eu",
                {
                    "CLOUD_DEPLOYMENT": "EU",
                    "SITE_URL": "https://eu.posthog.com",
                    "JS_URL": "https://app-static.eu.posthog.com",
                    "TASKS_AGENT_PROXY_PUBLIC_URL": "https://agent-proxy.eu.posthog.com/",
                },
                ("eu", "us"),
            ),
            # The named hosts and the config token are PostHog Cloud's, so another install that swapped
            # its wildcards for them would refuse loads from its own hosts.
            (
                "self_hosted_with_reporting_on",
                {
                    "CLOUD_DEPLOYMENT": None,
                    "SITE_URL": "https://posthog.example.com",
                    "CSP_REPORT_ENDPOINT": "https://posthog.example.com/report/?token=phc_test&v=2",
                },
                None,
            ),
        ]
    )
    def test_only_cloud_pages_swap_the_wildcards_for_named_posthog_hosts(
        self, _name: str, overrides: dict[str, str | None], regions: tuple[str, str] | None
    ) -> None:
        # Cloud enforces the app policy for everyone, so the enforced header is the one that must be narrowed.
        with override_settings(TEST=False, DEBUG=False, **overrides):
            response = self.client.get("/")

        # A self-hosted install only reports the policy.
        policy = response["Content-Security-Policy" if regions else "Content-Security-Policy-Report-Only"]
        directives = {name: sources for name, *sources in (part.split() for part in policy.split("; "))}
        script_src, connect_src = directives["script-src"], directives["connect-src"]
        style_src, font_src = directives["style-src"], directives["font-src"]
        (report_uri,) = directives["report-uri"]
        report_version = parse_qs(urlsplit(report_uri).query)["v"]
        wildcards = {"https://*.posthog.com", "https://*.i.posthog.com"}
        if not regions:
            assert wildcards <= set(script_src)
            assert "https://*.posthog.com" in style_src
            assert "https://*.posthog.com" in font_src
            # An operator's endpoint keeps the version they configured.
            assert report_version == ["2"]
            return

        region, other_region = regions
        assert not wildcards & {*script_src, *connect_src, *style_src, *font_src}
        # Under the wildcard policy's version, reports from the two policies mix in one query.
        assert report_version == ["4"]
        # The app cannot start without its bundle host.
        assert overrides["JS_URL"] in script_src
        assert "https://internal-cf.posthog.com/array/sTMFPsFhdP1Ssg/config.js" in script_src
        assert f"https://live.{region}.posthog.com" in connect_src
        assert f"https://webhooks.{region}.posthog.com" in connect_src
        assert f"https://{region}.i.posthog.com/decide/" in connect_src
        assert f"https://{region}.i.posthog.com/i/v0/e/" in connect_src
        # The bare origin would admit every endpoint on the ingestion host, not only the paths the app calls.
        assert f"https://{region}.i.posthog.com" not in connect_src
        assert f"https://agent-proxy.{region}.posthog.com" in connect_src
        # Allowing the other region would hide a request that crossed regions by mistake.
        assert not any(other_region in (urlsplit(source).hostname or "").split(".") for source in connect_src)
        # The app loads its stylesheets and fonts from the bundle host, and the toolbar loads its own from
        # /static/. Without either source the page renders unstyled, and the user sees no error.
        assert {overrides["JS_URL"], "https://internal-cf.posthog.com/static/"} <= set(style_src)
        assert {overrides["JS_URL"], "https://internal-cf.posthog.com/static/"} <= set(font_src)
        # The swap must remove the wildcard alone. Inline styles, data: fonts and Google Fonts still load.
        assert {"'self'", "'unsafe-inline'", "https://fonts.googleapis.com"} <= set(style_src)
        assert {"'self'", "data:", "https://fonts.gstatic.com"} <= set(font_src)

    @parameterized.expand(
        [
            (
                "enforced_app_page",
                "/",
                {"CLOUD_DEPLOYMENT": "US", "SITE_URL": "https://us.posthog.com", "JS_URL": _US_BUNDLE},
                True,
            ),
            # This document enforces the app policy, and the shadows must stay in the report-only header.
            (
                "enforced_embeddable_document",
                "/shared/notarealtoken",
                {"CLOUD_DEPLOYMENT": "US", "SITE_URL": "https://us.posthog.com", "JS_URL": _US_BUNDLE},
                True,
            ),
            (
                "self_hosted_with_reporting_on",
                "/",
                {
                    "CLOUD_DEPLOYMENT": None,
                    "SITE_URL": "https://posthog.example.com",
                    "CSP_REPORT_ENDPOINT": "https://posthog.example.com/report/?token=phc_test&v=2",
                },
                False,
            ),
        ]
    )
    def test_cloud_reports_narrower_sources_without_blocking_them(
        self, _name: str, path: str, overrides: dict[str, str | None], expects_shadows: bool
    ) -> None:
        with override_settings(TEST=False, DEBUG=False, E2E_TESTING=False, **overrides):
            response = self.client.get(path)

        enforced = _parse_policies(response.get("Content-Security-Policy", ""))
        reported = _parse_policies(response.get("Content-Security-Policy-Report-Only", ""))
        (app_policy,) = [policy for policy in enforced + reported if "default-src" in policy]
        # The app policy keeps `https:` and the PostHog wildcard, so the shadow reports images without blocking any.
        assert {"https:", "https://*.posthog.com"} <= set(app_policy["img-src"])
        # Enforced, the shadow would block every image from a host it does not name.
        assert [policy for policy in enforced if _report_version(policy) == ["7"]] == []
        # A v=5 report names an image that only `https:` admits. The image shadow also reports PostHog hosts the
        # named list misses, so under 5 its reports would mix with the old ones in one query.
        assert [policy for policy in enforced + reported if _report_version(policy) == ["5"]] == []
        # The app policy enforces the named stylesheet and font hosts, so a v=6 policy would report each miss twice.
        assert [policy for policy in enforced + reported if _report_version(policy) == ["6"]] == []
        image_shadows = [policy for policy in reported if _report_version(policy) == ["7"]]
        if not expects_shadows:
            assert image_shadows == []
            return

        (image_shadow,) = image_shadows
        # Any other directive would make a v=7 report mean something besides "this image host is not named".
        assert set(image_shadow) == {"img-src", "report-uri"}
        img_src = set(image_shadow["img-src"])
        # `https:` admits every host and the wildcard every PostHog host, so with either one a miss never reports.
        assert not {"https:", "https://*.posthog.com"} & img_src
        # Without these, every page load reports its own bundle or the toolbar, and a real miss is lost.
        assert {_US_BUNDLE, "https://internal-cf.posthog.com/static/"} <= img_src
        # The swap must remove those two sources alone, or every image the others admit reports as a miss.
        assert {"'self'", "data:", "blob:", "https://posthog.com", "https://www.gravatar.com"} <= img_src

    @override_settings(
        OBJECT_STORAGE_PUBLIC_ENDPOINT="https://s3.us-east-1.amazonaws.com",
        OBJECT_STORAGE_BUCKET="posthog-test-bucket",
    )
    def test_connect_src_admits_the_presigned_upload_endpoint(self) -> None:
        # Narrowing must keep it: cloud enforces the narrowed policy, and an upload it drops
        # fails in the browser with nothing logged server-side.
        with override_settings(
            TEST=False, DEBUG=False, CLOUD_DEPLOYMENT="US", SITE_URL="https://us.posthog.com", E2E_TESTING=False
        ):
            response = self.client.get("/")

        policy = response["Content-Security-Policy"]
        connect_src = next(part for part in policy.split("; ") if part.startswith("connect-src ")).split()
        assert "https://s3.us-east-1.amazonaws.com/posthog-test-bucket" in connect_src


@override_settings(CLOUD_DEPLOYMENT="LOCAL")
class TestAppCspHeaderName(SimpleTestCase):
    @parameterized.expand(
        [
            ("shared_dashboard", "/shared_dashboard/abc123", {}, True),
            ("shared", "/shared/abc123", {}, True),
            ("embedded", "/embedded/abc123", {}, True),
            ("render_query", "/render_query", {}, True),
            # A replay export can run an eval in a frame of this document, and an enforced policy refuses it.
            ("exporter_render", "/exporter", {}, False),
            # This route serves the shared page, so it enforces like /shared/.
            ("exporter_with_token", "/exporter/abc123", {}, True),
            # The survey view sets its own policy, so this is a response that the view did not build.
            ("external_survey", "/external_surveys/019efb7e-0672-0000-729b-e234586f6177", {}, False),
            # No route serves these, so the app catch-all answers them, and the app then runs in that
            # document like on any other page.
            ("unrouted_exporter_subpath", "/exporter/a/b", {}, True),
            ("unrouted_survey_subpath", "/external_surveys/a/b", {}, True),
            # A self-hosted install enforces nothing here, and that includes the frame-ancestors
            # header that an app page gets on such an install.
            ("shared_on_a_self_hosted_install", "/shared/abc123", {"CLOUD_DEPLOYMENT": None, "DEBUG": False}, False),
            # Cloud sends other report-only policies in the same header, and they must not replace
            # the app policy there.
            (
                "exporter_on_cloud",
                "/exporter",
                {
                    "TEST": False,
                    "DEBUG": False,
                    "E2E_TESTING": False,
                    "CLOUD_DEPLOYMENT": "US",
                    "SITE_URL": "https://us.posthog.com",
                    "JS_URL": _US_BUNDLE,
                },
                False,
            ),
        ]
    )
    def test_embeddable_document_sends_the_app_policy_without_frame_ancestors(
        self, _name: str, path: str, overrides: dict[str, str | bool | None], expects_enforced: bool
    ) -> None:
        def view(_request: HttpRequest) -> HttpResponse:
            return HttpResponse("<html><body>shared</body></html>", content_type="text/html; charset=utf-8")

        with override_settings(**overrides):
            response = CSPMiddleware(view)(RequestFactory().get(path))

        enforced = response.get("Content-Security-Policy", "")
        reported = response.get("Content-Security-Policy-Report-Only", "")
        assert ("default-src" in enforced, "default-src" in reported) == (expects_enforced, not expects_enforced)
        # A customer's site frames each of these, and the app policy names only PostHog origins in
        # frame-ancestors. Enforced, the directive stops the document rendering on their page.
        # Reported, it sends a report for every embed.
        assert "frame-ancestors" not in enforced + reported

    @parameterized.expand(
        [
            ("app_root", "/"),
            ("project_page", "/project/2/dashboard"),
            # Neither prefix owns these. A shorter prefix match would hand the app catch-all the
            # carve-out and quietly exempt an ordinary page from enforcement.
            ("shared_prefix_without_separator", "/sharedthing"),
            ("exporter_prefix_without_separator", "/exporterthing"),
        ]
    )
    def test_page_is_enforced(self, _name: str, path: str) -> None:
        assert app_csp_header_name(path) == "Content-Security-Policy"

    @parameterized.expand(
        [
            # A prefix match on /exporter would include this route, which serves the shared page.
            ("exporter_with_token", "/exporter/abc123"),
            ("shared", "/shared/abc123"),
            ("app_root", "/"),
        ]
    )
    @override_settings(
        TEST=False,
        DEBUG=False,
        E2E_TESTING=False,
        CLOUD_DEPLOYMENT="US",
        SITE_URL="https://us.posthog.com",
        JS_URL=_US_BUNDLE,
    )
    def test_only_the_exporter_render_asks_for_script_samples(self, _name: str, path: str) -> None:
        def view(_request: HttpRequest) -> HttpResponse:
            return HttpResponse("<html><body>page</body></html>", content_type="text/html; charset=utf-8")

        def script_src(request_path: str) -> list[str]:
            response = CSPMiddleware(view)(RequestFactory().get(request_path))
            policies = _parse_policies(response.get("Content-Security-Policy", "")) + _parse_policies(
                response.get("Content-Security-Policy-Report-Only", "")
            )
            (app_policy,) = [policy for policy in policies if "default-src" in policy]
            # Each response carries its own nonce.
            return [source for source in app_policy["script-src"] if not source.startswith("'nonce-")]

        exporter, other = script_src("/exporter"), script_src(path)
        # Without a sample, an eval report from a replay export render does not show which code ran.
        assert "'report-sample'" in exporter
        # A sample can carry page code to the report endpoint.
        assert "'report-sample'" not in other
        # Cloud rebuilds script-src when it narrows the wildcards, so the keyword must be the only difference.
        assert [source for source in exporter if source != "'report-sample'"] == other


class TestNarrowedAppPolicy(SimpleTestCase):
    def test_swaps_the_wildcards_and_keeps_every_other_source(self) -> None:
        app_policy = [
            "default-src 'self'",
            "script-src 'self' 'nonce-abc' 'wasm-unsafe-eval' https://*.posthog.com https://*.i.posthog.com https://js.stripe.com",
            "worker-src 'self' blob:",
            "img-src 'self' data: https://*.posthog.com",
            "connect-src 'self' https://api.github.com https://*.posthog.com",
        ]

        narrowed = narrowed_app_policy(
            app_policy,
            {
                "script-src": ["https://app-static-prod.posthog.com"],
                "connect-src": ["https://internal-j.posthog.com"],
            },
        )

        # This builds the enforced policy, so any directive or source it drops besides the wildcards
        # changes what the app can load. img-src keeps its wildcard because no list replaces it.
        assert narrowed == [
            "default-src 'self'",
            "script-src 'self' 'nonce-abc' 'wasm-unsafe-eval' https://js.stripe.com https://app-static-prod.posthog.com",
            "worker-src 'self' blob:",
            "img-src 'self' data: https://*.posthog.com",
            "connect-src 'self' https://api.github.com https://internal-j.posthog.com",
        ]


class TestObjectStorageUploadSource(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "shared_s3",
                "https://s3.us-east-1.amazonaws.com",
                "posthog-cloud-prod-us-east-1-app-assets",
                "https://s3.us-east-1.amazonaws.com/posthog-cloud-prod-us-east-1-app-assets",
            ),
            ("dev_store_keeps_http", "http://objectstorage:19000", "posthog", "http://objectstorage:19000/posthog"),
            ("endpoint_unset", "", "posthog", ""),
            ("bucket_unset", "https://s3.us-east-1.amazonaws.com", "", ""),
            ("not_a_fetchable_scheme", "s3://posthog-bucket", "posthog", ""),
        ]
    )
    def test_source_carries_the_bucket_or_is_left_out(
        self, _name: str, endpoint: str, bucket: str, expected: str
    ) -> None:
        with override_settings(OBJECT_STORAGE_PUBLIC_ENDPOINT=endpoint, OBJECT_STORAGE_BUCKET=bucket):
            assert object_storage_upload_source() == expected

    def test_a_plaintext_endpoint_is_named_over_https_outside_dev(self) -> None:
        # Only the dev store is reached over http. Anywhere else the policy must not bless a
        # bucket served in plaintext, whatever the endpoint is configured as.
        with override_settings(
            OBJECT_STORAGE_PUBLIC_ENDPOINT="http://storage.example.com",
            OBJECT_STORAGE_BUCKET="posthog",
            TEST=False,
            DEBUG=False,
        ):
            assert object_storage_upload_source() == "https://storage.example.com/posthog"


class TestViewManagedCsp(SimpleTestCase):
    @parameterized.expand(
        [
            # The workflow asset endpoint sandboxes captured email HTML and leaves frame-ancestors
            # open so the app can frame it. Enforcement must not replace that policy, because the
            # app policy drops the sandbox and names a frame-ancestors list the app origin does not
            # match, which blanks the viewer.
            ("custom_policy", "/", "sandbox; default-src 'none'", False),
            ("custom_admin", "/admin/", "default-src *", True),
            ("no_policy", "/", None, True),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_html_response_with_view_managed_csp(
        self, _name: str, path: str, policy: str | None, expects_reporting: bool
    ) -> None:
        def view(_request: HttpRequest) -> HttpResponse:
            response = HttpResponse("<html><body>artifact</body></html>", content_type="text/html; charset=utf-8")
            if policy is not None:
                response["Content-Security-Policy"] = policy
            return response

        request = RequestFactory().get(path)
        request.user = MagicMock(is_authenticated=True, distinct_id="abc", email="someone@posthog.com")
        response = CSPMiddleware(view)(request)

        if path == "/admin/":
            assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
            assert "default-src *" not in response["Content-Security-Policy"]
        elif policy is not None:
            assert response["Content-Security-Policy"] == policy
            assert "Content-Security-Policy-Report-Only" not in response
        else:
            assert response["Content-Security-Policy"].startswith("default-src 'self'")
        assert ("Reporting-Endpoints" in response) == expects_reporting
