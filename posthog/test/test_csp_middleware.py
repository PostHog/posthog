from urllib.parse import parse_qs, urlsplit

from posthog.test.base import APIBaseTest, override_settings
from unittest.mock import MagicMock, patch

from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.csp_middleware import (
    CSP_ENFORCE_OTHER_SIGNED_OUT_PAGES_FLAG,
    CSPMiddleware,
    app_csp_header_name,
    narrowed_app_policy,
)


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

    @parameterized.expand(
        [
            ("app_root", "/", True),
            # No route serves this path, so the app catch-all answers it. It must keep the app
            # policy, because the frame policy is enforced and its script-src 'none' stops the app
            # from starting.
            ("path_under_the_replay_frame_prefix", "/replay_player_frame", True),
            # A customer's page frames this document, and the enforced list names only PostHog
            # origins.
            ("embeddable_document", "/shared/notarealtoken", False),
        ]
    )
    def test_signed_out_page_without_the_flag_enforces_only_frame_ancestors(
        self, _name, path, enforces_frame_ancestors
    ):
        self.client.logout()
        response = self.client.get(path)
        reported = response["Content-Security-Policy-Report-Only"]
        assert "default-src 'self'" in reported
        if not enforces_frame_ancestors:
            assert "Content-Security-Policy" not in response
            return
        # Framing is enforced ahead of the flag because it is what lets posthog.com frame the app.
        # The enforced list has to be the one the reported policy names, or the two drift apart.
        enforced = response["Content-Security-Policy"]
        assert enforced.startswith("frame-ancestors https://posthog.com")
        assert "default-src" not in enforced
        assert enforced in reported

    def test_enforcement_reaches_an_app_page_but_not_an_embeddable_one(self):
        # The wiring guard for app_csp_header_name. The matrix of paths lives in
        # TestAppCspHeaderName, which needs no database.
        enforced = self.client.get("/")
        assert "default-src 'self'" in enforced["Content-Security-Policy"]
        assert "Content-Security-Policy-Report-Only" not in enforced

        embedded = self.client.get("/shared/notarealtoken")
        assert "Content-Security-Policy" not in embedded
        assert "frame-ancestors" not in embedded["Content-Security-Policy-Report-Only"]

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
        (report_uri,) = directives["report-uri"]
        report_version = parse_qs(urlsplit(report_uri).query)["v"]
        wildcards = {"https://*.posthog.com", "https://*.i.posthog.com"}
        if not regions:
            assert wildcards <= set(script_src)
            # An operator's endpoint keeps the version they configured.
            assert report_version == ["2"]
            return

        region, other_region = regions
        assert not wildcards & {*script_src, *connect_src}
        # Under the wildcard policy's version, reports from the two policies mix in one query.
        assert report_version == ["4"]
        # The app cannot start without its bundle host.
        assert overrides["JS_URL"] in script_src
        assert "https://internal-cf.posthog.com/array/sTMFPsFhdP1Ssg/config.js" in script_src
        assert f"https://live.{region}.posthog.com" in connect_src
        assert f"https://webhooks.{region}.posthog.com" in connect_src
        assert f"https://{region}.i.posthog.com/decide/" in connect_src
        assert f"https://agent-proxy.{region}.posthog.com" in connect_src
        # Allowing the other region would hide a request that crossed regions by mistake.
        assert not any(other_region in (urlsplit(source).hostname or "").split(".") for source in connect_src)


@override_settings(CLOUD_DEPLOYMENT="LOCAL")
class TestAppCspHeaderName(SimpleTestCase):
    def _request(
        self, path: str, *, distinct_id: str | None = "abc", email: str = "someone@posthog.com"
    ) -> HttpRequest:
        request = RequestFactory().get(path)
        request.user = MagicMock(is_authenticated=distinct_id is not None, distinct_id=distinct_id, email=email)
        return request

    @parameterized.expand(
        [
            ("shared_dashboard", "/shared_dashboard/abc123"),
            ("shared", "/shared/abc123"),
            ("embedded", "/embedded/abc123"),
            ("interview", "/interview/abc123"),
            ("exporter_with_token", "/exporter/abc123"),
            ("exporter_render", "/exporter"),
            ("render_query", "/render_query"),
            ("external_survey", "/external_surveys/019efb7e-0672-0000-729b-e234586f6177"),
        ]
    )
    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=True)
    def test_embeddable_document_stays_report_only_under_enforcement(self, _name, path, _mock_flag):
        # A customer's site frames each of these. The app policy names only PostHog origins in
        # frame-ancestors, so enforcing it here stops the document rendering on their page.
        assert app_csp_header_name(self._request(path)) == "Content-Security-Policy-Report-Only"
        assert app_csp_header_name(self._request(path, distinct_id=None)) == "Content-Security-Policy-Report-Only"

    @parameterized.expand(
        [
            ("app_root", "/", "abc", False),
            ("project_page", "/project/2/dashboard", "abc", False),
            # Neither prefix owns these. A shorter prefix match would hand the app catch-all the
            # carve-out and quietly exempt an ordinary page from enforcement.
            ("shared_prefix_without_separator", "/sharedthing", "abc", False),
            ("exporter_prefix_without_separator", "/exporterthing", "abc", False),
            ("login", "/login", None, False),
            ("signup", "/signup", None, False),
            ("reset_link", "/reset/abc/def", None, False),
            ("reset_2fa_link", "/reset_2fa/abc/def", None, False),
            ("verify_email_link", "/verify_email/abc/def", None, False),
            ("other_signed_out_page_with_the_flag", "/messaging-preferences/abc", None, True),
        ]
    )
    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled")
    def test_page_is_enforced(
        self, _name: str, path: str, distinct_id: str | None, flag_enabled: bool, mock_flag: MagicMock
    ) -> None:
        mock_flag.side_effect = lambda key, *args, **kwargs: (
            flag_enabled and key == CSP_ENFORCE_OTHER_SIGNED_OUT_PAGES_FLAG
        )
        assert app_csp_header_name(self._request(path, distinct_id=distinct_id)) == "Content-Security-Policy"

    @parameterized.expand(
        [
            ("other_signed_out_page", "/messaging-preferences/abc"),
            ("login_prefix_without_separator", "/loginfoo"),
        ]
    )
    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=False)
    def test_other_signed_out_page_stays_report_only_without_the_flag(self, _name: str, path: str, _mock_flag) -> None:
        assert app_csp_header_name(self._request(path, distinct_id=None)) == "Content-Security-Policy-Report-Only"

    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=False)
    def test_a_request_without_a_user_follows_the_signed_out_rules(self, _mock_flag: MagicMock) -> None:
        # CSPMiddleware runs before AuthenticationMiddleware, so a response from a middleware between
        # the two carries no request.user.
        assert app_csp_header_name(RequestFactory().get("/login")) == "Content-Security-Policy"
        assert (
            app_csp_header_name(RequestFactory().get("/messaging-preferences/abc"))
            == "Content-Security-Policy-Report-Only"
        )

    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=True)
    def test_each_signed_out_document_draws_its_own_bucket(self, mock_flag: MagicMock) -> None:
        app_csp_header_name(self._request("/messaging-preferences/abc", distinct_id=None))
        app_csp_header_name(self._request("/messaging-preferences/abc", distinct_id=None))
        # A fixed id would put every signed-out visitor in one bucket, so a rollout percentage
        # would enforce for everyone or nobody.
        first, second = (call.args[1] for call in mock_flag.call_args_list)
        assert first != second
        assert mock_flag.call_args.kwargs["only_evaluate_locally"] is True
        assert mock_flag.call_args.kwargs["send_feature_flag_events"] is False

    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", side_effect=Exception("flags unavailable"))
    def test_a_failing_flag_lookup_leaves_the_policy_report_only(self, _mock_flag: MagicMock) -> None:
        # Fail safe: an enforced policy that nobody meant to turn on breaks the page.
        assert (
            app_csp_header_name(self._request("/messaging-preferences/abc", distinct_id=None))
            == "Content-Security-Policy-Report-Only"
        )


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
