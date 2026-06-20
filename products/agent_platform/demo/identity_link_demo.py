#!/usr/bin/env python3
"""
End-to-end demo of agent identity linking against a LOCAL stack.

Creates + deploys an agent that needs a `dogs` OAuth credential, then drives the
whole flow (no browser needed): chat → auth_required link → OAuth authorize →
ingress callback → chat again → the agent calls the dog API as the linked user.

Set CHAT_AUTH=jwt (default, signs a JWT principal) or CHAT_AUTH=posthog (drives
the chat as your PostHog user via the PAT) — both are verified the same way.

Prereqs (all local):
  1. hogli running the agent stack (ingress :3030, runner) WITH this branch's code
     — restart agent-ingress + agent-runner so they pick up the identity wiring.
  2. The dog OAuth server running:
       cd products/agent_platform/services/agent-tests
       ../agent-runner/node_modules/.bin/tsx scripts/dog-oauth-server.ts      # :4545
  3. A PostHog personal API key for the local instance (Settings → Personal API keys),
     scoped to the project. Used only to create/deploy the agent + read sessions.

Run:
  POSTHOG_PAT=phx_xxx python3 products/agent_platform/demo/identity_link_demo.py
Optional env: TEAM_ID (default 1), POSTHOG_API (http://localhost:8010),
  INGRESS (http://localhost:3030), DOG (http://127.0.0.1:4545).
"""

# ruff: noqa: T201  — this is a CLI demo; printing its narrative is the point.

import os
import sys
import hmac
import json
import time
import base64
import hashlib
import urllib.error
import urllib.request

PAT = os.environ.get("POSTHOG_PAT")
TEAM_ID = os.environ.get("TEAM_ID", "1")
POSTHOG_API = os.environ.get("POSTHOG_API", "http://localhost:8010").rstrip("/")
INGRESS = os.environ.get("INGRESS", "http://localhost:3030").rstrip("/")
DOG = os.environ.get("DOG", "http://127.0.0.1:4545").rstrip("/")
JWT_SECRET = os.environ.get("JWT_SECRET", "demo-jwt-secret")

API = f"{POSTHOG_API}/api/projects/{TEAM_ID}"


def die(msg: str) -> None:
    print(f"\n✗ {msg}")
    sys.exit(1)


def req(
    method: str, url: str, body: dict | None = None, bearer: str | None = None, raw: bool = False
) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if bearer:
        r.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(r) as resp:
            text = resp.read().decode()
            return resp.status, (text if raw else (json.loads(text) if text else {}))
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        return e.code, text


def sign_jwt(sub: str) -> str:
    b64 = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    signing_input = f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64({'sub': sub})}"
    sig = (
        base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest())
        .rstrip(b"=")
        .decode()
    )
    return f"{signing_input}.{sig}"


def step(msg: str) -> None:
    print(f"\n▶ {msg}")


def main() -> None:
    if not PAT:
        die("Set POSTHOG_PAT to a local personal API key.")

    spec = {
        "model": "anthropic/claude-sonnet-4-6",
        "triggers": [
            {
                "type": "chat",
                "auth": {
                    "modes": [
                        {"type": "posthog", "audience": "project"},
                        {"type": "jwt", "issuer_secret_ref": "JWT_SECRET"},
                    ]
                },
            }
        ],
        "tools": [{"kind": "native", "id": "@posthog/identity-fetch"}],
        "identity_providers": [
            {
                "kind": "oauth2",
                "id": "dogs",
                "authorize_url": f"{DOG}/authorize",
                "token_url": f"{DOG}/token",
                "client_id": "dogs-client",
                "scopes": ["read:dog"],
                "userinfo_url": f"{DOG}/userinfo",
            }
        ],
    }
    agent_md = (
        "# Dog facts agent\n\n"
        "When the user asks about dogs, call `@posthog/identity-fetch` with "
        f"provider `dogs` and url `{DOG}/api/dog`. If it returns `auth_required`, "
        "reply with the `authorize_url` and ask the user to connect, then retry "
        "after they confirm."
    )

    step("Create application")
    st, app = req(
        "POST", f"{API}/agent_applications/", {"name": "Identity Link Demo", "description": "dogs OAuth"}, PAT
    )
    if st not in (200, 201):
        die(f"create app failed ({st}): {app}")
    slug = app["slug"]
    print(f"  app {app['id']}  slug={slug}")

    step("Create draft revision")
    st, rev = req("POST", f"{API}/agent_applications/{slug}/revisions/", {"spec": spec}, PAT)
    if st not in (200, 201):
        die(f"create revision failed ({st}): {rev}")
    rev_id = rev["id"]

    step("Set JWT secret (encrypted_env)")
    req(
        "POST", f"{API}/agent_applications/{slug}/revisions/{rev_id}/set_env/", {"env": {"JWT_SECRET": JWT_SECRET}}, PAT
    )

    step("Write agent.md (spec already set at revision create)")
    st, b = req("PUT", f"{API}/agent_applications/{slug}/revisions/{rev_id}/agent_md/", {"content": agent_md}, PAT)
    if st not in (200, 201):
        die(f"agent_md failed ({st}): {b}")

    step("Freeze + validate + promote")
    req("POST", f"{API}/agent_applications/{slug}/revisions/{rev_id}/freeze/", {}, PAT)
    st, v = req("POST", f"{API}/agent_applications/{slug}/revisions/{rev_id}/validate/", {}, PAT)
    if isinstance(v, dict) and v.get("ok") is False:
        die(f"validate failed: {json.dumps(v.get('errors'))}")
    st, p = req("POST", f"{API}/agent_applications/{slug}/revisions/{rev_id}/promote/", {}, PAT)
    if st not in (200, 201):
        die(f"promote failed ({st}): {p}")
    print(f"  live: {slug}")

    # ---- Drive the chat (no browser). CHAT_AUTH=jwt (default) or posthog. ----
    jwt = sign_jwt("demo-user-jwt")
    chat_auth = os.environ.get("CHAT_AUTH", "jwt")
    chat_bearer = PAT if chat_auth == "posthog" else jwt
    print(f"  principal: {chat_auth}")

    def poll_tool_result(session_id: str, want: str, tries: int = 40) -> dict | None:
        for _ in range(tries):
            st, s = req("GET", f"{API}/agent_applications/{slug}/sessions/{session_id}", bearer=PAT)
            convo = s.get("conversation", []) if isinstance(s, dict) else []
            for m in convo:
                if m.get("role") != "toolResult":
                    continue
                for blk in m.get("content", []):
                    txt = blk.get("text", "")
                    if want in txt:
                        try:
                            return json.loads(txt)
                        except Exception:
                            pass
            time.sleep(0.5)
        return None

    step(f"Chat /run ({chat_auth} principal): ask about dogs")
    st, run = req("POST", f"{INGRESS}/agents/{slug}/run", {"message": "what dogs do I have?"}, chat_bearer)
    if st != 200:
        die(f"/run failed ({st}): {run}")
    session_id = run["session_id"]
    print(f"  session {session_id}")

    step("Wait for auth_required link")
    gated = poll_tool_result(session_id, "auth_required")
    if not gated or "auth_required" not in gated:
        die(f"no auth_required surfaced; last tool result: {gated}")
    authorize_url = gated["auth_required"]["authorize_url"]
    print(f"  link: {authorize_url}")

    step("Complete OAuth (follow IdP /authorize → ingress callback)")
    # urllib follows the 302 from the IdP straight to our ingress callback, which
    # consumes the state, exchanges the code, and persists the linked credential.
    try:
        with urllib.request.urlopen(authorize_url) as resp:
            cb_status = resp.status
    except urllib.error.HTTPError as e:
        cb_status = e.code
    print(f"  callback → HTTP {cb_status}")
    if cb_status != 200:
        die("OAuth callback did not succeed")

    step("Chat /send: ask again, now linked")
    st, _ = req(
        "POST", f"{INGRESS}/agents/{slug}/send", {"session_id": session_id, "message": "now try again"}, chat_bearer
    )
    ok = poll_tool_result(session_id, '"status":200') or poll_tool_result(session_id, "breed")
    if not ok:
        die("no successful dog API call after linking")
    print(f"\n✅ DONE — the agent called the dog API as the linked user:\n   {json.dumps(ok)}")
    print(f"\nPostHog-user path: open agent '{slug}' in PostHog Code and chat — your")
    print("logged-in PostHog user is the linkable principal; same link flow applies.")


if __name__ == "__main__":
    main()
