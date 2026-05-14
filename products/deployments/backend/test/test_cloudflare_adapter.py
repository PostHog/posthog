from __future__ import annotations

from django.test import SimpleTestCase, override_settings

import requests
import responses
from parameterized import parameterized

from products.deployments.backend.adapters.cloudflare import (
    CLOUDFLARE_API_BASE,
    CLOUDFLARE_API_TIMEOUT_SECONDS,
    CFProject,
    CloudflareError,
    CloudflarePagesAdapter,
)

ACCOUNT_ID = "test-account-id"
PROJECT_PREFIX = "hogdev-"


@override_settings(
    DEPLOYMENTS_CLOUDFLARE_ACCOUNT_ID=ACCOUNT_ID,
    DEPLOYMENTS_CLOUDFLARE_API_TOKEN="test-token",
    DEPLOYMENTS_CLOUDFLARE_PROJECT_PREFIX=PROJECT_PREFIX,
)
class TestCloudflarePagesAdapter(SimpleTestCase):
    @responses.activate
    def test_create_project_posts_prefixed_name_and_attaches_hog_dev_domain(self) -> None:
        create_url = f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects"
        domain_url = f"{create_url}/{PROJECT_PREFIX}1-myapp/domains"
        responses.add(
            responses.POST,
            create_url,
            json={"success": True, "errors": [], "messages": [], "result": {"name": f"{PROJECT_PREFIX}1-myapp"}},
            status=200,
        )
        responses.add(
            responses.POST,
            domain_url,
            json={"success": True, "errors": [], "messages": [], "result": {"name": "1-myapp.hog.dev"}},
            status=200,
        )

        project = CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")

        self.assertEqual(project, CFProject(name=f"{PROJECT_PREFIX}1-myapp", subdomain="1-myapp.hog.dev"))
        self.assertEqual(len(responses.calls), 2)
        self.assertEqual(
            responses.calls[0].request.body,
            b'{"name": "hogdev-1-myapp", "production_branch": "main"}',
        )
        self.assertEqual(responses.calls[1].request.body, b'{"name": "1-myapp.hog.dev"}')
        # Bearer auth + request-path timeout.
        self.assertEqual(responses.calls[0].request.headers["Authorization"], "Bearer test-token")

    @responses.activate
    def test_create_project_raises_when_cloudflare_returns_success_false(self) -> None:
        responses.add(
            responses.POST,
            f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects",
            json={
                "success": False,
                "errors": [{"code": 1009, "message": "Project name already taken"}],
                "result": None,
            },
            status=200,
        )

        with self.assertRaises(CloudflareError) as cm:
            CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")
        self.assertIn("Project name already taken", str(cm.exception))

    @responses.activate
    def test_create_project_falls_back_when_cf_error_lacks_message_key(self) -> None:
        # Some CF responses come back with an `errors` array of dicts
        # that lack a `"message"` key — without a fallback, the user
        # would see `"Cloudflare API call failed: None (status 500)"`.
        responses.add(
            responses.POST,
            f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects",
            json={"success": False, "errors": [{"code": 9001}], "result": None},
            status=500,
        )

        with self.assertRaises(CloudflareError) as cm:
            CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")
        self.assertIn("Unknown error", str(cm.exception))
        self.assertNotIn("None", str(cm.exception))

    @responses.activate
    def test_create_project_error_does_not_leak_account_id(self) -> None:
        # CloudflareError is rendered into a public 502 response body by
        # the viewset, so the account ID (which appears in the API path)
        # must never end up in the exception message.
        responses.add(
            responses.POST,
            f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects",
            json={"success": False, "errors": [{"message": "boom"}], "result": None},
            status=500,
        )

        with self.assertRaises(CloudflareError) as cm:
            CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")
        self.assertNotIn(ACCOUNT_ID, str(cm.exception))

    @responses.activate
    def test_create_project_raises_on_http_error(self) -> None:
        responses.add(
            responses.POST,
            f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects",
            json={"success": False, "errors": [{"message": "Unauthorized"}], "result": None},
            status=401,
        )

        with self.assertRaises(CloudflareError) as cm:
            CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")
        self.assertIn("Unauthorized", str(cm.exception))
        self.assertIn("401", str(cm.exception))

    @responses.activate
    def test_create_project_raises_on_network_error(self) -> None:
        responses.add(
            responses.POST,
            f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects",
            body=requests.ConnectionError("connection refused"),
        )

        with self.assertRaises(CloudflareError) as cm:
            CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")
        self.assertIn("connection refused", str(cm.exception))

    @parameterized.expand(
        [
            ("missing_account_id", "", "test-token"),
            ("missing_api_token", ACCOUNT_ID, ""),
            ("both_missing", "", ""),
        ]
    )
    def test_create_project_raises_when_settings_missing(self, _name: str, account_id: str, api_token: str) -> None:
        with override_settings(
            DEPLOYMENTS_CLOUDFLARE_ACCOUNT_ID=account_id,
            DEPLOYMENTS_CLOUDFLARE_API_TOKEN=api_token,
        ):
            with self.assertRaises(CloudflareError) as cm:
                CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")
            self.assertIn("missing required settings", str(cm.exception))

    @responses.activate
    def test_create_project_does_not_attach_domain_if_create_call_fails(self) -> None:
        responses.add(
            responses.POST,
            f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects",
            json={"success": False, "errors": [{"message": "bad request"}], "result": None},
            status=400,
        )

        with self.assertRaises(CloudflareError):
            CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")
        # Only the create call should have been attempted.
        self.assertEqual(len(responses.calls), 1)

    @responses.activate
    def test_create_project_deletes_orphan_when_domain_attach_fails(self) -> None:
        # Create succeeds.
        create_url = f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects"
        project_url = f"{create_url}/{PROJECT_PREFIX}1-myapp"
        responses.add(
            responses.POST,
            create_url,
            json={"success": True, "errors": [], "messages": [], "result": {"name": f"{PROJECT_PREFIX}1-myapp"}},
            status=200,
        )
        # Domain attach fails.
        responses.add(
            responses.POST,
            f"{project_url}/domains",
            json={"success": False, "errors": [{"message": "domain conflict"}], "result": None},
            status=409,
        )
        # Cleanup DELETE succeeds.
        responses.add(
            responses.DELETE,
            project_url,
            json={"success": True, "errors": [], "messages": [], "result": {"id": f"{PROJECT_PREFIX}1-myapp"}},
            status=200,
        )

        with self.assertRaises(CloudflareError) as cm:
            CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")
        # The error surfaced is the domain-attach failure, not a delete-cleanup error.
        self.assertIn("domain conflict", str(cm.exception))
        # All three calls happened: create, attach, delete (cleanup).
        self.assertEqual(len(responses.calls), 3)
        self.assertEqual(responses.calls[2].request.method, "DELETE")

    @responses.activate
    def test_create_project_still_raises_original_error_if_cleanup_also_fails(self) -> None:
        create_url = f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects"
        project_url = f"{create_url}/{PROJECT_PREFIX}1-myapp"
        responses.add(
            responses.POST,
            create_url,
            json={"success": True, "errors": [], "messages": [], "result": {"name": f"{PROJECT_PREFIX}1-myapp"}},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{project_url}/domains",
            json={"success": False, "errors": [{"message": "domain attach failed"}], "result": None},
            status=500,
        )
        responses.add(
            responses.DELETE,
            project_url,
            json={"success": False, "errors": [{"message": "cleanup also failed"}], "result": None},
            status=500,
        )

        with self.assertRaises(CloudflareError) as cm:
            CloudflarePagesAdapter().create_project(name="1-myapp", production_branch="main")
        # User-facing error is still the attach failure — cleanup error is logged, not raised.
        self.assertIn("domain attach failed", str(cm.exception))
        self.assertNotIn("cleanup also failed", str(cm.exception))

    @responses.activate
    def test_rollback_returns_deployment_from_response(self) -> None:
        url = f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects/hogdev-1-myapp/deployments/dep-old/rollback"
        responses.add(
            responses.POST,
            url,
            json={
                "success": True,
                "errors": [],
                "messages": [],
                "result": {"id": "dep-new", "url": "https://hogdev-1-myapp.pages.dev"},
            },
            status=200,
        )

        deployment = CloudflarePagesAdapter().rollback(project_name="hogdev-1-myapp", deployment_id="dep-old")

        self.assertEqual(deployment.id, "dep-new")
        self.assertEqual(deployment.url, "https://hogdev-1-myapp.pages.dev")

    @responses.activate
    def test_rollback_raises_when_response_missing_url(self) -> None:
        responses.add(
            responses.POST,
            f"{CLOUDFLARE_API_BASE}/accounts/{ACCOUNT_ID}/pages/projects/p/deployments/d/rollback",
            json={"success": True, "errors": [], "messages": [], "result": {"id": "dep-new"}},
            status=200,
        )

        with self.assertRaises(CloudflareError) as cm:
            CloudflarePagesAdapter().rollback(project_name="p", deployment_id="d")
        self.assertIn("no deployment URL", str(cm.exception))


class TestCloudflareApiConstants(SimpleTestCase):
    def test_timeout_is_short_enough_for_request_path(self) -> None:
        # Sanity: the timeout exists for a reason — keep it small enough
        # that a hanging CF API doesn't drag the user-facing POST handler
        # past typical browser timeouts.
        self.assertLessEqual(CLOUDFLARE_API_TIMEOUT_SECONDS, 15)
