from urllib.parse import urlsplit

from posthog.test.base import APIBaseTest, override_settings
from unittest.mock import MagicMock, patch

from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.csp_middleware import (
    CSP_ENFORCE_APP_POLICY_FLAG,
    CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG,
    CSPMiddleware,
    app_csp_header_name,
    narrowed_app_policy,
)


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
        assert "frame-src 'self' https:" in response["Content-Security-Policy-Report-Only"]

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
        assert expected in response["Content-Security-Policy-Report-Only"]

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
    def test_html_response_without_the_flag_enforces_only_frame_ancestors(self, _name, path, enforces_frame_ancestors):
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

    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=True)
    def test_enforcement_reaches_an_app_page_but_not_an_embeddable_one(self, _mock_flag):
        # The wiring guard for app_csp_header_name. The matrix of paths lives in
        # TestAppCspHeaderName, which needs no database.
        enforced = self.client.get("/")
        assert "default-src 'self'" in enforced["Content-Security-Policy"]
        assert "Content-Security-Policy-Report-Only" not in enforced

        embedded = self.client.get("/shared/notarealtoken")
        assert "Content-Security-Policy" not in embedded
        assert "frame-ancestors" in embedded["Content-Security-Policy-Report-Only"]

    @override_settings(CLOUD_DEPLOYMENT="US")  # As PostHog Cloud
    def test_html_response_declares_default_reporting_endpoint_with_distinct_id(self):
        response = self.client.get("/")
        policy = response["Content-Security-Policy-Report-Only"]
        # A `report-to` directive makes browsers ignore `report-uri` and report through the
        # Reporting API, which drops violations raised in about:blank and srcdoc frames.
        assert "report-to" not in policy
        _, report_endpoint = next(part for part in policy.split("; ") if part.startswith("report-uri ")).split()
        assert report_endpoint.startswith("https://us.i.posthog.com/report/")
        assert f"distinct_id={self.user.distinct_id}" in report_endpoint
        # Browsers only deliver crash reports to the endpoint named `default`, so dropping or
        # renaming it silently stops crash ingestion.
        assert response["Reporting-Endpoints"] == f'default="{report_endpoint}"'

    @override_settings(CLOUD_DEPLOYMENT="US")  # As PostHog Cloud
    def test_reporting_endpoints_omit_distinct_id_when_logged_out(self):
        self.client.logout()
        response = self.client.get("/login")
        policy = response["Content-Security-Policy-Report-Only"]
        assert "report-uri https://us.i.posthog.com/report/" in policy
        assert "distinct_id" not in policy
        header = response["Reporting-Endpoints"]
        assert 'default="https://us.i.posthog.com/report/' in header
        assert "distinct_id" not in header

    @parameterized.expand(
        [
            ("self_hosted_by_default", {"CLOUD_DEPLOYMENT": None, "DEBUG": False}),
            # DEBUG puts an install in the local run mode rather than the hobby one, and nothing
            # stops a self-hoster deploying that way, so it must report nowhere as well.
            ("self_hosted_with_debug", {"CLOUD_DEPLOYMENT": None, "DEBUG": True}),
            # Cloud would otherwise report, so this case proves the empty value turns it off.
            ("explicitly_disabled", {"CLOUD_DEPLOYMENT": "US", "CSP_REPORT_ENDPOINT": ""}),
        ]
    )
    def test_no_endpoint_still_sends_the_policy_but_asks_for_no_reports(self, _name, overrides):
        # A self-hosted install must not report to PostHog, and the policy itself must survive, so
        # dropping it here would silently remove a security control.
        with override_settings(**{"CSP_REPORT_ENDPOINT": None, **overrides}):
            response = self.client.get("/")
        policy = response["Content-Security-Policy-Report-Only"]
        assert "default-src 'self'" in policy
        assert "report-uri" not in policy
        assert "report-to" not in policy
        assert "Reporting-Endpoints" not in response

    @override_settings(CSP_REPORT_ENDPOINT="https://posthog.example.com/report/")
    def test_report_endpoint_is_configurable(self):
        # An operator can point reporting at their own install, so nothing may hardcode ours.
        response = self.client.get("/")
        policy = response["Content-Security-Policy-Report-Only"]
        assert "report-uri https://posthog.example.com/report/?sample_rate=0.1" in policy
        header = response["Reporting-Endpoints"]
        assert "us.i.posthog.com" not in header
        assert f"distinct_id={self.user.distinct_id}" in header

    @parameterized.expand(
        [
            ("staff", True, "1", "0.1"),
            ("not_staff", False, "0.1", "1"),
        ]
    )
    @override_settings(CSP_REPORT_ENDPOINT="https://posthog.example.com/report/")
    def test_staff_report_every_violation_while_everyone_else_is_sampled(
        self, _name, is_staff, expected_rate, other_rate
    ):
        # Staff get the policy enforced ahead of everyone else, so a violation of theirs is
        # something already broken for a colleague rather than one sample of a trend. At 0.1 nine
        # in ten of those never arrive, which defeats the point of rolling out to staff first.
        self.user.is_staff = is_staff
        self.user.save()

        response = self.client.get("/")

        policy = response["Content-Security-Policy-Report-Only"]
        assert f"report-uri https://posthog.example.com/report/?sample_rate={expected_rate}" in policy
        assert f"sample_rate={expected_rate}&distinct_id={self.user.distinct_id}" in policy
        assert f"sample_rate={other_rate}" not in policy

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
            # Sampling the admin policy too would silently drop violations, so the branches diverge.
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
        assert "frame-ancestors 'none'" not in response["Content-Security-Policy"]
        assert "connect-src 'self'" in response["Content-Security-Policy-Report-Only"]

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
            # An operator can turn reporting on for their own install, but the shadow names PostHog
            # Cloud's hosts and token, so its reports would tell that operator nothing they can act on.
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
    def test_only_cloud_pages_carry_a_report_only_shadow_without_the_wildcards(self, _name, overrides, regions):
        # The shadow is the evidence for dropping the wildcards, so it must report on its own version
        # and must not quietly keep a wildcard.
        with override_settings(TEST=False, DEBUG=False, **overrides):
            response = self.client.get("/")

        app_policy, *shadows = response["Content-Security-Policy-Report-Only"].split(", ")
        assert "https://*.posthog.com" in app_policy
        assert "&v=2&" in app_policy
        assert len(shadows) == (1 if regions else 0)
        if regions:
            region, other_region = regions
            shadow = shadows[0]
            assert "*.posthog.com" not in shadow
            assert "https://internal-cf.posthog.com/array/sTMFPsFhdP1Ssg/config.js" in shadow
            assert "&v=3&" in shadow
            connect_src = next(part for part in shadow.split("; ") if part.startswith("connect-src ")).split()
            assert f"https://live.{region}.posthog.com" in connect_src
            assert f"https://{region}.i.posthog.com/decide/" in connect_src
            assert f"https://agent-proxy.{region}.posthog.com" in connect_src
            # Allowing the other region would hide a request that crossed regions by mistake.
            assert not any(other_region in (urlsplit(source).hostname or "").split(".") for source in connect_src)


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
            ("app_root", "/"),
            ("project_page", "/project/2/dashboard"),
            # Neither prefix owns these. A shorter prefix match would hand the app catch-all the
            # carve-out and quietly exempt an ordinary page from enforcement.
            ("shared_prefix_without_separator", "/sharedthing"),
            ("exporter_prefix_without_separator", "/exporterthing"),
        ]
    )
    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=True)
    def test_ordinary_page_is_enforced_for_a_flagged_user(self, _name, path, _mock_flag):
        assert app_csp_header_name(self._request(path)) == "Content-Security-Policy"

    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=False)
    def test_ordinary_page_stays_report_only_without_the_flag(self, _mock_flag):
        assert app_csp_header_name(self._request("/")) == "Content-Security-Policy-Report-Only"

    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=True)
    def test_the_flag_lookup_carries_the_email_for_local_evaluation(self, mock_flag):
        # Local evaluation cannot resolve a condition on email unless the caller supplies it, so a
        # staff-only rollout would enforce nothing.
        app_csp_header_name(self._request("/", email="staff@posthog.com"))
        assert mock_flag.call_args.kwargs["person_properties"] == {"email": "staff@posthog.com"}
        # Local evaluation keeps a flag network call out of every HTML response.
        assert mock_flag.call_args.kwargs["only_evaluate_locally"] is True

    @parameterized.expand(
        [
            ("login", "/login", None, CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG, "Content-Security-Policy"),
            ("signup", "/signup", None, CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG, "Content-Security-Policy"),
            ("reset_link", "/reset/abc/def", None, CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG, "Content-Security-Policy"),
            (
                "reset_2fa_link",
                "/reset_2fa/abc/def",
                None,
                CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG,
                "Content-Security-Policy",
            ),
            (
                "verify_email_link",
                "/verify_email/abc/def",
                None,
                CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG,
                "Content-Security-Policy",
            ),
            ("login_without_a_flag", "/login", None, None, "Content-Security-Policy-Report-Only"),
            (
                "login_with_the_app_flag",
                "/login",
                None,
                CSP_ENFORCE_APP_POLICY_FLAG,
                "Content-Security-Policy-Report-Only",
            ),
            ("signed_in", "/login", "abc", CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG, "Content-Security-Policy-Report-Only"),
            (
                "other_signed_out_page",
                "/messaging-preferences/abc",
                None,
                CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG,
                "Content-Security-Policy-Report-Only",
            ),
            (
                "login_prefix_without_separator",
                "/loginfoo",
                None,
                CSP_ENFORCE_SIGNED_OUT_PAGES_FLAG,
                "Content-Security-Policy-Report-Only",
            ),
        ]
    )
    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled")
    def test_each_flag_enforces_only_its_own_pages(
        self,
        _name: str,
        path: str,
        distinct_id: str | None,
        enabled_flag: str | None,
        expected: str,
        mock_flag: MagicMock,
    ) -> None:
        mock_flag.side_effect = lambda key, *args, **kwargs: key == enabled_flag
        assert app_csp_header_name(self._request(path, distinct_id=distinct_id)) == expected

    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=True)
    def test_each_signed_out_document_draws_its_own_bucket(self, mock_flag: MagicMock) -> None:
        app_csp_header_name(self._request("/login", distinct_id=None))
        app_csp_header_name(self._request("/login", distinct_id=None))
        # A fixed id would put every signed-out visitor in one bucket, so a rollout percentage
        # would enforce for everyone or nobody.
        first, second = (call.args[1] for call in mock_flag.call_args_list)
        assert first != second
        assert mock_flag.call_args.kwargs["only_evaluate_locally"] is True
        assert mock_flag.call_args.kwargs["send_feature_flag_events"] is False

    @parameterized.expand([("signed_in", "abc"), ("signed_out", None)])
    @patch("posthog.csp_middleware.posthoganalytics.feature_enabled", side_effect=Exception("flags unavailable"))
    def test_a_failing_flag_lookup_leaves_the_policy_report_only(
        self, _name: str, distinct_id: str | None, _mock_flag: MagicMock
    ) -> None:
        # Fail safe: an enforced policy that nobody meant to turn on breaks the page.
        assert (
            app_csp_header_name(self._request("/login", distinct_id=distinct_id))
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

        # A source the shadow dropped besides the wildcards would report loads the app policy allows,
        # and a directive it was not asked about would restrict what the shadow does not measure.
        assert narrowed == [
            "script-src 'self' 'nonce-abc' 'wasm-unsafe-eval' https://js.stripe.com https://app-static-prod.posthog.com",
            # Without it, workers fall back to script-src and the shadow reports the app's blob: workers.
            "worker-src 'self' blob:",
            "connect-src 'self' https://api.github.com https://internal-j.posthog.com",
        ]


class TestViewManagedCsp(SimpleTestCase):
    @parameterized.expand(
        [
            ("custom_policy", "/", False, "default-src 'self'", False),
            # The workflow asset endpoint sandboxes captured email HTML and leaves frame-ancestors
            # open so the app can frame it. Enforcement must not replace that policy, because the
            # app policy drops the sandbox and names a frame-ancestors list the app origin does not
            # match, which blanks the viewer.
            ("custom_policy_under_enforcement", "/", True, "sandbox; default-src 'none'", False),
            ("custom_admin", "/admin/", False, "default-src *", True),
            ("no_policy", "/", False, None, True),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_html_response_with_view_managed_csp(
        self, _name: str, path: str, enforced: bool, policy: str | None, expects_reporting: bool
    ) -> None:
        def view(_request: HttpRequest) -> HttpResponse:
            response = HttpResponse("<html><body>artifact</body></html>", content_type="text/html; charset=utf-8")
            if policy is not None:
                response["Content-Security-Policy"] = policy
            return response

        request = RequestFactory().get(path)
        request.user = MagicMock(is_authenticated=True, distinct_id="abc", email="someone@posthog.com")
        with patch("posthog.csp_middleware.posthoganalytics.feature_enabled", return_value=enforced):
            response = CSPMiddleware(view)(request)

        if path == "/admin/":
            assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
            assert "default-src *" not in response["Content-Security-Policy"]
        elif policy is not None:
            assert response["Content-Security-Policy"] == policy
        else:
            assert response["Content-Security-Policy"].startswith("frame-ancestors ")
        assert ("Content-Security-Policy-Report-Only" in response) == (expects_reporting and path != "/admin/")
        assert ("Reporting-Endpoints" in response) == expects_reporting
