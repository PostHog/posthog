# Troubleshooting Support Slack local setup

The walls you actually hit, in the order they tend to appear, plus a way to verify the event path without
touching Slack.

## Failure modes

| Symptom                                                                                                                                       | Cause / fix                                                                                                                                                                                                                                                                                                                                                                                                              |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Error: Support Slack OAuth client ID is not configured` (503 from `authorize`)                                                               | `SUPPORT_SLACK_APP_CLIENT_ID` is empty. Set the three `SUPPORT_SLACK_*` vars in `.env.local` and restart the backend. If still empty, a blank value stored in constance overrides the env default — set it at `/admin/constance/config/` instead.                                                                                                                                                                        |
| Slack: "redirect_uri did not match any configured URIs"                                                                                       | The exact callback URL isn't in the Slack app's **Redirect URLs**. Add `http://localhost:8010/api/conversations/v1/slack/callback` (matches `SITE_URL`) and click **Save URLs**. Match is exact: scheme, host, port, path.                                                                                                                                                                                               |
| Slack: "requesting permission to install a bot ... but it's not currently configured with a bot"                                              | No bot user on the app. Slack app → **App Home** → enable a bot user with a display name.                                                                                                                                                                                                                                                                                                                                |
| OAuth returns to the callback URL as a **white page** (URL bar still on `/slack/callback`)                                                    | The callback ran without a session. The callback needs an authenticated session on the origin `SITE_URL` resolves to. Log in on that same origin before connecting. The blank look is the `401` JSON being hidden by its `Content-Security-Policy: default-src 'none'`.                                                                                                                                                  |
| Any page over the tunnel is a **white page**, and `curl https://<tunnel>/_preflight` returns `200` with an **empty body** and `server: Caddy` | The tunnel isn't rewriting the upstream `Host` to `localhost`, so the dev Caddy (which only answers for the `localhost` host) drops through to nothing. Add the host rewrite: ngrok `--host-header=localhost` (or `host_header: localhost` in the config), cloudflared `--http-host-header localhost`. A correct hit shows `server: granian`.                                                                            |
| Lots of **"Network error — There was an issue loading the requested resource"** across the SPA when browsing over the tunnel                  | Free-tier tunnel rate limiting. The ngrok request inspector shows many `/api/...` calls with status `0` (dropped). The SPA fires dozens of requests per scene, past `ngrok-free.app`'s per-minute cap. Fix: don't browse the SPA over the tunnel — keep the app and OAuth on `localhost`, and use the tunnel only for inbound events (low volume). Or switch to Cloudflare Tunnel (no such limit), or a paid ngrok plan. |
| Events reach the tunnel but no ticket appears                                                                                                 | Check the celery worker log for `process_supporthog_event`, and confirm `team_exists_for_slack_workspace` matches the `slack_team_id` saved by your OAuth connect. Also confirm the bot is in the channel.                                                                                                                                                                                                               |

## Two things that look like problems but aren't

- **`http://localhost:8234` assets from an https tunnel page.** Browsers treat `localhost` as a secure
  context, so those dev-server scripts and the `ws://localhost:8234` HMR socket are not blocked as mixed
  content. The white page over a tunnel is the Host-header issue above, not mixed content.
- **Region routing proxying your events away.** In `DEBUG`, `PRIMARY_REGION_DOMAIN` is `urlparse(SITE_URL).netloc`
  (`products/conversations/backend/services/region_routing.py`). With `SITE_URL=http://localhost:8010` the
  primary is `localhost:8010`, but the tunnel rewrites Host to `localhost`, so `is_primary_region` is false
  and `slack_events.py` processes the event locally instead of proxying. If you ever set the tunnel to
  forward the port too, the host would match and events would proxy to `localhost:8000` — keep the rewrite
  at bare `localhost`.

## Verify the event path without Slack

Because `validate_support_request` (`products/conversations/backend/support_slack.py`) is standard Slack
HMAC signing, you can replay exactly what Slack sends on save — a signed `url_verification` — and confirm
the whole path (tunnel → Caddy → Django → signature check → handler) works. A `{"challenge": ...}` response
with `server: granian` proves it end to end and isolates any problem away from Slack's config.

```bash
SECRET=$(grep '^SUPPORT_SLACK_SIGNING_SECRET=' .env.local | cut -d= -f2)
TS=$(date +%s)
BODY='{"type":"url_verification","challenge":"local-test-123"}'
SIG="v0=$(printf '%s' "v0:${TS}:${BODY}" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}')"
curl -sS -i -X POST "https://<tunnel-host>/api/conversations/v1/slack/events" \
  -H "Content-Type: application/json" \
  -H "X-Slack-Request-Timestamp: ${TS}" \
  -H "X-Slack-Signature: ${SIG}" \
  --data "$BODY"
```

- `{"challenge": "local-test-123"}` + `server: granian` → path is good; if real events still don't arrive,
  the Slack app's Event Subscriptions Request URL isn't pointed at the tunnel.
- `403 Invalid request` → the secret used to sign the request doesn't match the backend's active signing
  secret. The command signs with the `.env.local` value, but the backend uses the Constance-stored value
  when one exists, so this can 403 even against a correctly configured backend. Causes: `.env.local` not
  loaded, backend not restarted after editing it, or a different value saved in Constance
  (`/admin/constance/config/`). Sign with the active (Constance) value if one is set, or clear it so the env
  default applies.
- empty `200`, `server: Caddy` → Host-header rewrite missing (see the table).
- no response / status `0` → tunnel dropped it (rate limit or tunnel down).

## Watching real events

The tunnel's request inspector (`http://localhost:4040` for ngrok) shows each Slack POST and its response.
A real `event_callback` returns `202` (accepted and enqueued, `slack_events.py:98`); `url_verification`
returns `200`. `X-Slack-Retry-Num` on a request means Slack is retrying because a previous delivery didn't
`200`/`202` in time.
