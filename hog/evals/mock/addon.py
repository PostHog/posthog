"""A fake PostHog for hog evals, served through mitmproxy.

hog keeps its default host (us.posthog.com), so the agent sees the same region notes and links as a
real user. Only PostHog's app, ingestion and release hosts are intercepted; everything else (GitHub
skill downloads, npm, model APIs) is tunnelled untouched.

The port the container's HTTPS_PROXY points at picks the scenario, so one proxy serves every eval.
Each device login gets its own project, so a session's later calls can be found by project id.
"""

import os
import re
import gzip
import json
import time
import base64
import secrets
import itertools
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mitmproxy import http

LOG_DIR = Path(os.environ.get("MOCK_LOG_DIR", "/logs"))
MANIFEST = Path(os.environ.get("MOCK_MANIFEST", "/mock/manifest.json"))
CATALOG = Path(os.environ.get("MOCK_CATALOG", "/mock/catalog.json"))

# Seconds after the login starts before the fake user acts on the approval page.
APPROVE_AFTER_S = float(os.environ.get("MOCK_APPROVE_AFTER_S", "4"))

SCENARIOS = {
    18080: {"name": "approve", "login": "approve", "events": 12},
    18081: {"name": "never", "login": "never", "events": 0},
    18082: {"name": "denied", "login": "deny", "events": 0},
    18083: {"name": "quiet", "login": "approve", "events": 0},
}

APP_HOSTS = {"us.posthog.com", "eu.posthog.com"}
INGEST_HOSTS = {"us.i.posthog.com", "eu.i.posthog.com"}
PASSTHROUGH_PATHS = ("/static/",)

_lock = threading.RLock()
_ids = itertools.count(100_001)
logins: dict[str, dict] = {}  # device_code -> login
tokens: dict[str, int] = {}  # access or refresh token -> project id
projects: dict[int, dict] = {}


def scenario_of(flow: http.HTTPFlow) -> dict:
    port = flow.client_conn.sockname[1] if flow.client_conn.sockname else 0
    return SCENARIOS.get(port, SCENARIOS[18080]) | {"port": port}


def log(kind: str, flow: http.HTTPFlow, scenario: dict, **extra) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "kind": kind,
        "scenario": scenario["name"],
        "method": flow.request.method,
        "host": flow.request.pretty_host,
        "path": flow.request.path,
        **extra,
    }
    with _lock, open(LOG_DIR / "requests.jsonl", "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def respond(flow: http.HTTPFlow, status: int, body, content_type="application/json") -> None:
    data = body if isinstance(body, (bytes, str)) else json.dumps(body)
    flow.response = http.Response.make(status, data, {"Content-Type": content_type})


def form(flow: http.HTTPFlow) -> dict:
    ctype = flow.request.headers.get("content-type", "")
    if "json" in ctype:
        try:
            return json.loads(flow.request.get_text() or "{}")
        except ValueError:
            return {}
    return {k: v[0] for k, v in parse_qs(flow.request.get_text() or "").items()}


def body_json(flow: http.HTTPFlow):
    try:
        return json.loads(flow.request.get_text() or "null")
    except ValueError:
        return None


def bearer(flow: http.HTTPFlow) -> str | None:
    auth = flow.request.headers.get("authorization", "")
    return auth[7:] if auth.lower().startswith("bearer ") else None


def new_project() -> dict:
    pid = next(_ids)
    project = {
        "id": pid,
        "uuid": f"0190a000-0000-7000-8000-{pid:012d}",
        "name": "Default project",
        "organization": "0190a000-0000-7000-8000-000000000001",
        "api_token": "phc_" + secrets.token_urlsafe(30).replace("-", "a"),
        "timezone": "UTC",
        "session_recording_opt_in": False,
        "capture_console_log_opt_in": False,
        "autocapture_exceptions_opt_in": False,
        "product_intents": [],
        "is_demo": False,
        "completed_snippet_onboarding": False,
        "ingested_event": False,
    }
    projects[pid] = project
    return project


def issue_tokens(project_id: int, scope: str) -> dict:
    access = "pha_" + secrets.token_urlsafe(32)
    refresh = "phr_" + secrets.token_urlsafe(32)
    tokens[access] = project_id
    tokens[refresh] = project_id
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": scope,
        "scoped_teams": [project_id],
    }


def device_authorization(flow, scenario):
    fields = form(flow)
    device_code = secrets.token_urlsafe(24)
    user_code = "-".join(secrets.token_hex(2).upper() for _ in range(2))
    host = flow.request.pretty_host
    logins[device_code] = {
        "started": time.time(),
        "scenario": scenario["name"],
        "scope": fields.get("scope", ""),
        "polls": 0,
        "project": None,
        "user_code": user_code,
    }
    log("login_started", flow, scenario, user_code=user_code, scopes=len(fields.get("scope", "").split()))
    respond(
        flow,
        200,
        {
            "device_code": device_code,
            "user_code": user_code,
            "verification_uri": f"https://{host}/device",
            "verification_uri_complete": f"https://{host}/device?code={user_code}",
            "expires_in": 600,
            "interval": 2,
        },
    )


def token(flow, scenario):
    fields = form(flow)
    grant = fields.get("grant_type", "")
    if grant.endswith("device_code"):
        login = logins.get(fields.get("device_code", ""))
        if login is None:
            log("login_poll_unknown", flow, scenario)
            return respond(flow, 400, {"error": "invalid_grant"})
        login["polls"] += 1
        waited = time.time() - login["started"]
        behaviour = SCENARIOS_BY_NAME[login["scenario"]]["login"]
        if behaviour == "never" or waited < APPROVE_AFTER_S:
            return respond(flow, 400, {"error": "authorization_pending"})
        if behaviour == "deny":
            log("login_denied", flow, scenario, user_code=login["user_code"], polls=login["polls"])
            return respond(flow, 400, {"error": "access_denied"})
        if login["project"] is None:
            login["project"] = new_project()["id"]
        log(
            "login_approved",
            flow,
            scenario,
            project=login["project"],
            user_code=login["user_code"],
            polls=login["polls"],
        )
        return respond(flow, 200, issue_tokens(login["project"], login["scope"]))
    if grant == "refresh_token":
        pid = tokens.get(fields.get("refresh_token", ""))
        if pid is None:
            return respond(flow, 400, {"error": "invalid_grant"})
        log("token_refreshed", flow, scenario, project=pid)
        return respond(flow, 200, issue_tokens(pid, fields.get("scope", "")))
    log("token_unsupported_grant", flow, scenario, grant=grant)
    respond(flow, 400, {"error": "unsupported_grant_type"})


SCENARIOS_BY_NAME = {s["name"]: s for s in SCENARIOS.values()}
PROJECT_PATH = re.compile(r"^/api/(?:organizations/[^/]+/)?(?:environments|projects)/(\d+|@current)/(.*)$")


def api(flow, scenario):
    path = urlparse(flow.request.path).path
    token_value = bearer(flow)
    pid = tokens.get(token_value or "")
    if pid is None:
        log("api_unauthenticated", flow, scenario)
        return respond(
            flow, 401, {"type": "authentication_error", "code": "not_authenticated", "detail": "Invalid token."}
        )
    project = projects[pid]

    if path in ("/api/users/@me/",):
        log("api", flow, scenario, project=pid)
        return respond(
            flow,
            200,
            {
                "uuid": "0190a000-0000-7000-8000-0000000000aa",
                "email": "new-user@example.com",
                "first_name": "Sam",
                "distinct_id": "mock-user",
                "organization": {"id": project["organization"], "name": "Sam's organization"},
                "team": {"id": pid, "name": project["name"]},
            },
        )

    if path.rstrip("/") == "/api/personal_api_keys/@current":
        # The MCP tool handlers behind `hog api call` read the caller's access from here.
        log("api", flow, scenario, project=pid)
        return respond(
            flow,
            200,
            {"scopes": ["*"], "scoped_teams": [pid], "scoped_organizations": [project["organization"]]},
        )

    match = PROJECT_PATH.match(path)
    if match:
        requested, rest = match.groups()
        if requested != "@current" and int(requested) != pid:
            log("api_wrong_project", flow, scenario, project=pid, requested=requested)
            return respond(
                flow,
                403,
                {
                    "type": "authentication_error",
                    "code": "permission_denied",
                    "detail": "You don't have access to the project.",
                },
            )
        body = body_json(flow)
        if rest == "":
            if flow.request.method == "PATCH" and isinstance(body, dict):
                project.update(body)
                log("project_updated", flow, scenario, project=pid, fields=body)
            else:
                log("api", flow, scenario, project=pid)
            return respond(flow, 200, project)
        if rest == "add_product_intent/":
            intent = (body or {}).get("product_type")
            project["product_intents"].append({"product_type": intent})
            log("product_intent", flow, scenario, project=pid, product=intent)
            return respond(flow, 200, project)
        if rest == "product_enablement/" and flow.request.method == "POST":
            # The server owns each recipe, as in posthog/api/product_enablement.py.
            fields = {"session_replay": "session_recording_opt_in", "error_tracking": "autocapture_exceptions_opt_in"}
            results = {}
            for product in (body or {}).get("products", []):
                field = fields.get(product)
                if field is None:
                    continue
                results[product] = "already_enabled" if project[field] else "enabled"
                project[field] = True
            log("product_enabled", flow, scenario, project=pid, results=results)
            return respond(flow, 200, {"results": results})
        if rest.startswith("releases/flag_suggestions"):
            # `create-feature-flag` reads this right after it creates the flag, and reports the whole call
            # as failed when the answer has no `current` list.
            log("api_generic", flow, scenario, project=pid, body=None)
            return respond(flow, 200, {"current": [], "suggestions": [], "auto_release": False})
        if rest.startswith("query"):
            query = ((body or {}).get("query") or {}).get("query", "")
            count = scenario["events"] if "count()" in query and "from events" in query else 0
            log("query", flow, scenario, project=pid, query=query[:300], answered=count)
            return respond(
                flow,
                200,
                {"results": [[count]], "columns": ["count()"], "types": [["count()", "UInt64"]], "is_cached": False},
            )

    # Anything else an agent reaches through `hog api`: record it and answer like an empty project.
    body = body_json(flow)
    log("api_generic", flow, scenario, project=pid, body=body)
    if flow.request.method == "GET":
        return respond(flow, 200, {"results": [], "count": 0, "next": None, "previous": None})
    if flow.request.method == "DELETE":
        return respond(flow, 204, b"")
    echo = body if isinstance(body, dict) else {}
    return respond(flow, 201 if flow.request.method == "POST" else 200, {"id": next(_ids), **echo})


def ingestion(flow, scenario):
    raw = flow.request.raw_content or b""
    events = None
    try:
        data = raw
        if flow.request.headers.get("content-encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            data = gzip.decompress(raw)
        text = data.decode()
        if text.startswith("data="):
            text = base64.b64decode(parse_qs(text)["data"][0]).decode()
        parsed = json.loads(text)
        batch = parsed.get("batch", [parsed]) if isinstance(parsed, dict) else parsed
        events = [{"event": e.get("event"), "properties": e.get("properties")} for e in batch if isinstance(e, dict)]
    except Exception:  # noqa: BLE001 - an unreadable body is still logged by size
        pass
    log("ingest", flow, scenario, events=events, bytes=len(raw))
    if "/flags" in flow.request.path or "/decide" in flow.request.path:
        return respond(flow, 200, {"featureFlags": {}, "featureFlagPayloads": {}, "errorsWhileComputingFlags": False})
    respond(flow, 200, {"status": 1})


class FakePostHog:
    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = urlparse(flow.request.path).path
        scenario = scenario_of(flow)

        if host == "releases.posthog.com" and path.endswith("/latest/manifest.json"):
            log("release_manifest", flow, scenario)
            return respond(flow, 200, MANIFEST.read_bytes())
        if host in INGEST_HOSTS:
            return ingestion(flow, scenario)
        if host not in APP_HOSTS:
            return
        if path == "/api/cli/catalog.json":
            log("catalog", flow, scenario)
            return respond(flow, 200, CATALOG.read_bytes())
        if path.startswith(PASSTHROUGH_PATHS):
            log("passthrough", flow, scenario)
            return
        with _lock:
            if path == "/oauth/device-authorization/":
                return device_authorization(flow, scenario)
            if path == "/oauth/token/":
                return token(flow, scenario)
        if path == "/oauth/revoke/":
            log("token_revoked", flow, scenario)
            return respond(flow, 200, {})
        if path.startswith("/device"):
            # Only an agent that tries to approve its own login lands here; a person would use a browser.
            log("device_page_opened", flow, scenario, user_agent=flow.request.headers.get("user-agent"))
            return respond(
                flow,
                200,
                "<html><body><h1>Log in to PostHog</h1><p>Log in or sign up to approve this code.</p></body></html>",
                "text/html",
            )
        if path.startswith("/api/"):
            return api(flow, scenario)
        log("unmocked", flow, scenario)
        respond(flow, 404, {"detail": "Not mocked."})


addons = [FakePostHog()]
