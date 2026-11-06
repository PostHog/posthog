---
name: setting-up-support-slack-locally
description: >
  Connect a real Slack workspace to local PostHog Conversations (the SupportHog Slack app) so Slack
  messages become support tickets and replies post back. Use when the user wants to test the conversations
  Slack integration locally, hits "Support Slack OAuth client ID is not configured", gets a white screen or
  "Network error" on the OAuth callback, or asks how to set SUPPORT_SLACK_APP_CLIENT_ID / a tunnel for
  supporthog Slack events. Covers the Slack app + scopes, the SUPPORT_SLACK_* dynamic settings, and the
  key split: localhost for OAuth and the UI, a public tunnel only for inbound events.
---

# Setting up Support Slack locally

Slack is SaaS-only, so "local" means a throwaway Slack workspace + app whose OAuth and events reach your
laptop. The job has one non-obvious idea that avoids almost every wall: **the OAuth connect and the event
webhook have opposite reachability needs, so you point them at different places.**

- **OAuth connect** is browser-mediated. Your browser follows the redirect, so `localhost` is reachable.
  No tunnel needed.
- **Inbound events** (Slack POSTing messages so they become tickets) are server-to-server from Slack's
  cloud. Slack cannot reach `localhost`, so this one needs a public tunnel.

Keep the whole app and the OAuth flow on `localhost`, and point only Event Subscriptions (and Interactivity)
at the tunnel. This also sidesteps free-tier tunnel rate limits, since the tunnel then carries only Slack's
low-volume event POSTs rather than the entire SPA.

This is the conversations/SupportHog variant of the general
[Slack local setup guide](../../../docs/internal/slack-local-setup-guide.md); that guide covers the
PostHog Desktop / notifications Slack app (`SLACK_APP_*`, `/integrations/slack/callback`). Conversations uses
its own `SUPPORT_SLACK_*` credentials and `/api/conversations/v1/slack/*` routes, but the tunnel and
`SITE_URL` mechanics are identical.

## The endpoints

All under `products/conversations/backend/api/urls.py`, prefixed `/api/conversations/`:

| Route                    | Purpose                                                       | Reachability             |
| ------------------------ | ------------------------------------------------------------- | ------------------------ |
| `v1/slack/authorize`     | returns the Slack OAuth URL (auth-gated)                      | browser (localhost)      |
| `v1/slack/callback`      | OAuth redirect target; built from `SITE_URL`, no forced https | browser (localhost)      |
| `v1/slack/events`        | inbound event webhook, built on `posthog/ingress/`            | Slack's servers (tunnel) |
| `v1/slack/interactivity` | interactive component callbacks                               | Slack's servers (tunnel) |

The callback requires an authenticated session on whatever origin `SITE_URL` resolves to, because the
session cookie is per-origin. Keep `SITE_URL` on `localhost` and log in there, and the callback keeps your
session.

## Step 1 — credentials

`SUPPORT_SLACK_APP_CLIENT_ID`, `SUPPORT_SLACK_APP_CLIENT_SECRET`, and `SUPPORT_SLACK_SIGNING_SECRET` are
django-constance dynamic settings (`posthog/settings/dynamic_settings.py`) that default to the matching env
var. Empty client id is what produces "Support Slack OAuth client ID is not configured". Put your Slack
app's values in `.env.local` (gitignored) and restart the backend:

```bash
SUPPORT_SLACK_APP_CLIENT_ID=<client id>
SUPPORT_SLACK_APP_CLIENT_SECRET=<client secret>
SUPPORT_SLACK_SIGNING_SECRET=<signing secret>
```

Constance stores values in the DB, and a stored value overrides the env default. If it still reads as
unconfigured after a restart, check `/admin/constance/config/` for a blank stored value and set it there
instead.

## Step 2 — the Slack app

At [api.slack.com/apps](https://api.slack.com/apps), create an app in a throwaway workspace, then:

1. **App Home** → enable a **bot user** (give it a display name). Without this, install fails with "requesting
   permission to install a bot ... but it's not currently configured with a bot".
2. **OAuth & Permissions → Bot Token Scopes** — the flow requests these (from `SUPPORTHOG_SLACK_SCOPES` in
   `products/conversations/backend/api/slack_oauth.py`): `channels:history`, `channels:read`, `chat:write`,
   `chat:write.customize`, `files:read`, `files:write`, `groups:history`, `groups:read`, `reactions:read`,
   `users:read`, `users:read.email`. Attachments need the two `files:` scopes in both directions, so a
   workspace installed without them shows a "reconnect" banner in support settings.
3. **OAuth & Permissions → Redirect URLs** — add `http://localhost:8010/api/conversations/v1/slack/callback`
   and Save. If Slack refuses a plain-http localhost URL, use the tunnel URL for the callback too and log in
   once on the tunnel origin (see [references/troubleshooting.md](references/troubleshooting.md)).
4. Copy the Client ID, Client Secret, and Signing Secret from Basic Information into `.env.local` (Step 1).

## Step 3 — tunnel for inbound events

Run any HTTPS tunnel pointed at Caddy on **8010**, rewriting the upstream `Host` header to `localhost` (the
dev Caddy only answers for the `localhost` host; without the rewrite you get an empty `200` and a white page):

```bash
ngrok http --host-header=localhost 8010
# or, free with no rate limit:
cloudflared tunnel --url http://localhost:8010 --http-host-header localhost
```

Verify it reaches Django, not just Caddy:

```bash
curl -sS https://<tunnel-host>/_preflight | head -c 120   # want JSON, server: granian
```

Then in the Slack app set **Event Subscriptions → Request URL** (and **Interactivity → Request URL** if
testing buttons) to `https://<tunnel-host>/api/conversations/v1/slack/events` (and `.../interactivity`).
Slack sends a synchronous `url_verification` challenge on save, so the backend must be up; the handler
echoes it back automatically.

The Request URL alone only passes verification; it delivers nothing until you subscribe to events. Under
**Event Subscriptions → Subscribe to bot events**, add the events the backend handles (`SLACK_EVENT_TYPES`
in `posthog/ingress/slack/provider.py`, which is also what the consumer registers for):

- `app_mention`
- `message.channels` (and `message.groups` for private channels), both arriving as the inner `message` event
- `reaction_added`
- `member_joined_channel`, `member_left_channel`

Reinstall the app after changing scopes/events so the new grants take effect.

## Region routing, locally

The events endpoint is an ingress view: `products/conversations/backend/api/slack_events.py` wires the Slack
provider into `build_webhook_view()`, and ingress verifies the signature, parses the envelope and hands each
delivery to the `conversations_slack` consumer.

Which region handles a delivery is two separate answers:

1. The consumer's ownership lookup, `slack_delivery_ownership` in
   `products/conversations/backend/services/slack_events.py`. A workspace this database is connected to is
   `LOCAL`; a workspace it does not know is `ELSEWHERE`.
2. The ingress forward, which replays the signed request to `SECONDARY_REGION_DOMAIN` when any consumer
   answered `ELSEWHERE` **and** the request arrived on the primary region. See
   [Regional forwarding](../../../posthog/ingress/README.md#regional-forwarding).

`posthog/regions.py` holds both domains, and under `DEBUG` it rewrites them: the primary becomes
`urlparse(SITE_URL).netloc` (`localhost:8010` with the default dev `SITE_URL`) and the secondary becomes
`localhost:8000`.

The old handler also had a `DEBUG`-only shortcut that forwarded from the primary region even when the local
database held the workspace. That is gone. Ownership answers from the data alone in every environment, so a
workspace your local stack is connected to is always handled locally.

To exercise the forward on your laptop you need all three of: a request whose `Host` is the primary domain, a
`team_id` no local team is connected to, and something listening on `localhost:8000`. The tunnel cannot give
you the first, because the host rewrite makes the request arrive as bare `localhost`, which is not
`localhost:8010`. So sign a body yourself and POST it straight at `http://localhost:8010/...` (the snippet in
[references/troubleshooting.md](references/troubleshooting.md) signs one for you) with an unknown `team_id`.
Without a second stack on `localhost:8000` the forward fails and the endpoint answers `502`, which is still
proof that the forward was attempted; with one, the delivery lands there.

## Step 4 — connect and test

Browse the app at `http://localhost:8010`, log in, go to Support settings, and connect Slack. The OAuth
round-trip completes on localhost. Then invite the bot to a channel in your dev workspace and post a
message; it should arrive as a ticket, and a reply from the ticket should post back to the thread.

For the failure modes worth recognizing (white screen, "Network error", redirect mismatch, region routing),
see [references/troubleshooting.md](references/troubleshooting.md).
