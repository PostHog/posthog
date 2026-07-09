# Slack local setup guide

How to point a real Slack workspace at your local PostHog so you can test the **PostHog Code**
coding agent (`@PostHog <task>` → sandbox run) end to end. The same tunnel + workspace works for
the other Slack integrations too, but this guide only documents what we verified.

Slack is SaaS-only: there's no self-hosted Slack. So "local testing" means a real
(throwaway) Slack workspace + app whose webhooks and OAuth callback reach your laptop
through a tunnel. This guide captures a setup that has been verified end to end.

> Prerequisite: the PostHog Code stack must already work locally — GitHub App, temporal
> worker, sandboxes. If you haven't done that yet, follow
> [sandboxes-setup-guide.md](./sandboxes-setup-guide.md) first and come back here.

## How requests flow

Understanding this makes the two non-obvious config steps (ngrok `host_header` and
`SITE_URL`) self-explanatory.

```text
Slack  ──HTTPS──▶  ngrok edge  ──▶  ngrok agent (laptop)  ──▶  Caddy :8010  ──▶  Django :8000
(events,                                                       (dev proxy)       (web)
 interactivity,
 OAuth callback)
```

- Everything Slack needs — the event webhook, the interactivity callback, the OAuth
  redirect, and the PostHog UI — is served by **Caddy on port 8010** (the dev proxy that
  `hogli start` runs). Port 8000 is Django direct and does **not** serve the frontend.
- The dev Caddy only answers for the `localhost` host (`${CADDY_HOST:-http://localhost:8000}`
  in `docker-compose.dev.yml`). A request arriving with `Host: <you>.ngrok.dev` falls
  through to nothing and you get `200 OK` with an **empty body**. That's why the tunnel
  must rewrite the Host header to `localhost` (Step 1).
- The OAuth `redirect_uri` is built **server-side** from `SITE_URL`, not from the browser
  address bar (`OauthIntegration.redirect_uri()` in `posthog/models/integration.py`), and it
  force-upgrades the scheme to https — `SITE_URL.replace('http://', 'https://')`. `SITE_URL`
  defaults to `http://localhost:8010` (`posthog/settings/__init__.py:69`), so at that default
  Slack is handed `https://localhost:8010/...` — which has no TLS, hence the browser SSL error.
  Point it at your tunnel for the OAuth step (Step 3).

## Step 1 — ngrok tunnel into Caddy

You need a stable public HTTPS URL. Slack lists ngrok as its preferred tunnel, so that's what
this guide uses (a Hobbyist plan covers a few reserved domains) — but any HTTPS tunnel works.
Cloudflare Tunnel (`cloudflared`) is a fine free alternative; whatever you pick, point it at
**8010** (Caddy) and make it rewrite the upstream `Host` header to `localhost` (see "How requests
flow" for why).

ngrok config — point the tunnel at **8010** and set `host_header: localhost`:

```yaml
# ~/Library/Application Support/ngrok/ngrok.yml   (macOS)
# ~/.config/ngrok/ngrok.yml                        (Linux)
version: '3'
tunnels:
  app:
    proto: http
    addr: 8010
    domain: <you>-posthog.ngrok.dev # a domain you've reserved in the ngrok dashboard
    host_header: localhost # REQUIRED — see "How requests flow" above
agent:
  authtoken: <your-ngrok-authtoken>
```

```bash
ngrok start --all
```

Verify the tunnel reaches Django through Caddy:

```bash
curl -sS https://<you>-posthog.ngrok.dev/_preflight | jq .
```

You want real JSON back (the response header is `server: granian`). If you get an empty
body with `server: Caddy`, the `host_header` rewrite is missing or the domain isn't
actually bound — fix that before continuing.

> **Modal sandboxes:** this single Caddy tunnel is enough for Slack. Modal sandboxes
> reach PostHog over the public URL and work fine through Caddy, so you do **not** need a
> separate `:8000` tunnel for the Slack flow. If you're _also_ testing Modal sandboxes,
> keep your existing `gateway` (3308) and `mcp` (8787) tunnels — they're independent of
> this one. See the [sandbox guide](./sandboxes-setup-guide.md#tunnel-gateway-api-and-mcp).

## Step 2 — create the Slack app

1. Create a throwaway Slack workspace (e.g. `posthog-slack-dev-<you>`). You need admin to
   install apps.
2. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app
   manifest** → pick your workspace → paste the manifest below (swap in your domain):

```yaml
display_information:
  name: posthog-slack-dev
features:
  bot_user:
    display_name: posthog-slack-dev
    always_online: true
  app_home:
    home_tab_enabled: true
    messages_tab_enabled: false
    messages_tab_read_only_enabled: false
oauth_config:
  redirect_urls:
    - https://<you>-posthog.ngrok.dev/integrations/slack/callback
    - https://<you>-posthog.ngrok.dev/complete/slack-link/
  scopes:
    bot:
      - app_mentions:read
      - channels:read
      - groups:read
      - channels:history
      - groups:history
      - chat:write
      - canvases:write
      - files:write
      - reactions:write
      - users:read
      - users:read.email
    user:
      - identity.basic
      - identity.email
settings:
  event_subscriptions:
    request_url: https://<you>-posthog.ngrok.dev/slack/event-callback
    bot_events:
      - app_mention
      - app_home_opened
  interactivity:
    is_enabled: true
    request_url: https://<you>-posthog.ngrok.dev/slack/interactivity-callback
  org_deploy_enabled: false
  socket_mode_enabled: false
```

When you click **Create**, Slack verifies the event URL with a synchronous `challenge` POST, so
Django must be up at that moment.

3. From **Basic Information**, copy the **Client ID**, **Client Secret**, and **Signing Secret**.

> `link_shared` is left out on purpose — it needs the `links:read` scope (the manifest won't save
> otherwise) and the coding agent doesn't use it.

> The `app_home` block + `app_home_opened` bot event power the App Home tab; the
> sign-in-with-Slack flow needs `user` scopes `identity.basic` + `identity.email` and the second
> redirect URL (`/complete/slack-link/`). Drop those if you don't want either feature locally —
> they're behind the `slack-app-home` and `slack-app-oauth` flags.

## Step 3 — backend credentials and `SITE_URL`

PostHog Code reuses the regular Slack notifications app, so set the standard
`SLACK_APP_*` credentials in `.env` and restart the `django` +
`temporal-django-worker` processes so it reloads. These are dynamic settings
seeded from the env on boot (`posthog/settings/dynamic_settings.py`):

```bash
SLACK_APP_CLIENT_ID=<client id>
SLACK_APP_CLIENT_SECRET=<client secret>
SLACK_APP_SIGNING_SECRET=<signing secret>
```

Confirm the backend picked them up:

```bash
curl -sS https://<you>-posthog.ngrok.dev/_preflight | jq '.slack_service'
# => { "available": true, "client_id": "...." }
```

`SITE_URL` must point at your tunnel for the OAuth step (Step 5), or the redirect goes to
`https://localhost:8010/...` and the browser fails with an SSL error. It only matters during
OAuth, so you don't have to commit it to `.env` — a plain `export` in the shell that runs the
stack is enough, and the connected integration keeps working afterwards (until you re-auth) even
if you drop it:

```bash
export SITE_URL=https://<you>-posthog.ngrok.dev   # then (re)start the stack from this shell
```

Put it in `.env` instead if you want it to survive restarts from a fresh shell.

> There's also an `NGROK_URL` env var that `redirect_uri()` checks before `SITE_URL` in DEBUG —
> it would override just the OAuth redirect and leave `SITE_URL` alone. We used `SITE_URL` and
> didn't exercise the `NGROK_URL` path, so treat it as untested.

## Step 4 — feature flags

One flag gates the UI: `tasks` (shows the Tasks scene and gates task creation —
`products/tasks/backend/access.py`). It's an active flag in
`frontend/src/lib/constants.tsx`, so the normal local sync enables it at 100%:

```bash
python manage.py sync_feature_flags
```

If you already sync flags the usual way locally, it's likely on already — nothing to do.
(`setup_background_agents` also turns on `tasks` as part of the sandbox setup.) The
Slack mention webhook itself is not flag-gated — once the `slack` integration is
connected, `@PostHog` events reach the agent unconditionally.

## Step 5 — connect the integrations

**Slack.** PostHog Code piggybacks on the regular Slack notifications install — there's no
separate "PostHog Code Slack" install anymore. Go to **Settings → Project → Integrations**,
find Slack, click **Connect to Slack**, and authorize in your dev workspace. The PostHog Code
agent reads the same `Integration` row that the notifications product writes. Verify:

```bash
python manage.py shell -c "from posthog.models.integration import Integration; \
print(list(Integration.objects.filter(kind='slack').values('id','team_id','integration_id')))"
# => [{'id': ..., 'team_id': 1, 'integration_id': 'T0........'}]
```

The `tasks` flag from Step 4 still gates the Tasks UI on top of the connected integration.

**GitHub** (Settings → Integrations): connect a _team_ GitHub with at least one repo (otherwise
the repo cascade has nothing to pick and creates a no-repo task), and connect your _personal_
GitHub under User → Personal integrations (otherwise the task parks behind a "Connect GitHub"
button before the agent runs).

## Step 6 — Slack user → PostHog user

`resolve_slack_user` matches your Slack profile email to a PostHog org member. Locally this is
handled for you: a `DEBUG` branch (`products/slack_app/backend/api.py:417-419`) forces the email
to `test@posthog.com`, which is the default local dev user — so resolution works out of the box.
If your local user has a different email, point that branch (or your user's email) at it.

## Step 7 — smoke test

In a channel in your dev workspace:

```text
/invite @posthog-slack-dev
@posthog-slack-dev add a comment to the README explaining how to run tests
```

(The real @-handle is whatever Slack assigned — type `@p` and let autocomplete confirm.)

A successful run reacts 🌱 `:seedling:` on your message and posts a threaded "Working on task… ⏳"
with a **View agent logs** button — that's what we saw. You may also see 🔍 `:mag:` first, but only
when the repo-discovery agent has to choose among repos (a no-repo prompt skips it, as ours did).

Follow-ups — reply in-thread with another `@mention` — are forwarded to the running sandbox and
should react 👀 → 🦔 (or ❌ if the sandbox is gone). Expected from the code; not verified in our run.

## Debugging

- **ngrok request inspector** (`http://127.0.0.1:4040`) — confirms Slack's webhook actually reached
  you and shows the response. A `202` here means the event arrived and the problem is downstream;
  this is how we confirmed delivery during setup.
- **Temporal Web** (`http://localhost:8233`, filter workflow type
  `posthog-code-slack-mention-processing`) — shows which activity the run reached. The happy path
  ends at `create_posthog_code_task_for_repo_activity`.
- Going deeper, the `django` / `temporal-django-worker` logs carry `posthog_code_*` structlog
  lines, and Slack's app **Event Deliveries** page shows delivery failures — neither was needed in
  our run, but they're there if you get stuck.

## Troubleshooting

The walls we actually hit and fixed:

| Symptom                                                              | Cause / fix                                                                                                                                      |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `curl /_preflight` returns `200` with an empty body, `server: Caddy` | The tunnel reaches Caddy but isn't sending `Host: localhost`, so Caddy doesn't match its site block. Add `host_header: localhost` to the tunnel. |
| OAuth → browser `ERR_SSL_PROTOCOL_ERROR` on `localhost:8010`         | `SITE_URL` is still the localhost default. Point it at your https tunnel and restart django (Step 3).                                            |
| OAuth → "redirect_uri did not match any configured URIs"             | The Slack app's **Redirect URLs** must include `https://<tunnel>/integrations/slack/callback` — add it **and click Save URLs**.                  |
| Manifest won't save: "link_shared is missing scope links:read"       | Remove `link_shared` from `bot_events` (Step 2).                                                                                                 |
