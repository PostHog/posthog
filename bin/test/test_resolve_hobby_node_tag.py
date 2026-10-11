import os
import json
import tempfile
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import unittest

TOKEN = "anonymous-pull-token"


class FakeRegistry(HTTPServer):
    """Speaks just enough of the registry v2 API: a bearer-token challenge on /v2/,
    a token endpoint, and manifest HEAD requests for the tags it was told exist."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), FakeRegistryHandler)
        self.node_tags: set[str] = set()
        self.manifest_requests: list[str] = []
        self.token_scopes: list[str] = []

    @property
    def registry_url(self) -> str:
        return f"127.0.0.1:{self.server_port}/posthog/posthog"


class FakeRegistryHandler(BaseHTTPRequestHandler):
    server: FakeRegistry

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/v2/":
            self.send_response(401)
            realm = f"http://127.0.0.1:{self.server.server_port}/token"
            self.send_header("WWW-Authenticate", f'Bearer realm="{realm}",service="fake-registry"')
            self.end_headers()
        elif self.path.startswith("/token?"):
            self.server.token_scopes.append(self.path.split("scope=", 1)[1])
            body = json.dumps({"token": TOKEN}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self) -> None:
        prefix = "/v2/posthog/posthog-node/manifests/"
        if not self.path.startswith(prefix):
            self.send_response(404)
        elif self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_response(401)
        else:
            tag = self.path[len(prefix) :]
            self.server.manifest_requests.append(tag)
            self.send_response(200 if tag in self.server.node_tags else 404)
        self.end_headers()


class TestResolveHobbyNodeTag(unittest.TestCase):
    resolver = Path(__file__).resolve().parents[1] / "helpers" / "resolve-hobby-node-tag.sh"

    def setUp(self) -> None:
        self.registry = FakeRegistry()
        threading.Thread(target=self.registry.serve_forever, daemon=True).start()
        self.addCleanup(self.registry.server_close)
        self.addCleanup(self.registry.shutdown)
        self.checkout = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.checkout], check=True))
        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        subprocess.run(["git", "init", "-q", "-b", "master", self.checkout], check=True, env=git_env)
        for n in range(6):
            subprocess.run(
                ["git", "-C", self.checkout, "commit", "-q", "--allow-empty", "-m", f"commit {n}"],
                check=True,
                env=git_env,
            )
        # Newest first, like the walk: commits[0] is HEAD.
        self.commits = subprocess.run(
            ["git", "-C", self.checkout, "rev-list", "--first-parent", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()

    def resolve(self, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.resolver)],
            text=True,
            capture_output=True,
            env={
                "PATH": os.environ["PATH"],
                "REGISTRY_URL": self.registry.registry_url,
                "POSTHOG_CHECKOUT": self.checkout,
                **env,
            },
        )

    def test_picks_the_newest_ancestor_with_a_node_image(self) -> None:
        self.registry.node_tags = {self.commits[3], self.commits[5]}
        for app_tag in (self.commits[0], "latest"):
            with self.subTest(app_tag=app_tag):
                self.registry.manifest_requests.clear()
                result = self.resolve(POSTHOG_APP_TAG=app_tag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), self.commits[3])
                self.assertEqual(self.registry.manifest_requests, self.commits[:4])
        self.assertEqual(self.registry.token_scopes, ["repository:posthog/posthog-node:pull"] * 2)

    def test_walk_starts_at_the_app_commit_not_head(self) -> None:
        self.registry.node_tags = {self.commits[1], self.commits[4]}
        result = self.resolve(POSTHOG_APP_TAG=self.commits[2])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), self.commits[4])

    def test_pinned_tag_skips_the_registry(self) -> None:
        result = self.resolve(POSTHOG_APP_TAG="latest", POSTHOG_NODE_TAG="pr-123")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "pr-123")
        self.assertEqual(self.registry.manifest_requests, [])

    def test_falls_back_to_latest_with_a_warning_when_nothing_matches(self) -> None:
        self.registry.node_tags = {self.commits[4]}
        result = self.resolve(POSTHOG_APP_TAG=self.commits[0], HOBBY_NODE_TAG_MAX_COMMITS="3")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "latest")
        self.assertEqual(self.registry.manifest_requests, self.commits[:3])
        self.assertIn("No posthog-node image matches", result.stderr)
        self.assertIn("POSTHOG_NODE_TAG=<tag>", result.stderr)
