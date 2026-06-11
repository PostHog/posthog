# Plan: chart images in Slack insight link unfurls

Status: plan only — not yet implemented.

## Goal

When someone pastes a PostHog insight (or dashboard) link in Slack, the unfurl should include an image of the chart, not just title/type/description.

## What exists today

Two halves of this feature already exist, but they have never been joined:

1. **Text-only unfurls for internal insight links** — `products/slack_app/backend/slack_link_unfurl.py`. `handle_posthog_link_unfurl()` handles `link_shared` events arriving at `POST /slack/event-callback` (`products/slack_app/backend/api.py`). It parses `/project/<id>/insights/<short_id>` (and `/i/<short_id>`, plus `/dashboard/<id>`), looks the resource up by `short_id` on the Slack-connected team, and calls `chat.unfurl` with a Block Kit payload containing title, insight type, and description. No image block.
2. **Image-based unfurls for public share links** — legacy path in `ee/tasks/slack.py`, reached via the older `POST /integrations/slack/events` endpoint. For `/shared/<token>` URLs it creates an `ExportedAsset`, runs the image exporter, and unfurls with a Slack `image` block. So "screenshot an insight and unfurl it" is proven code — it is just gated on the link being a public share link.

### Screenshot pipeline (answers "how do we capture canvas charts?")

`products/exports/backend/tasks/image_exporter.py` drives headless Chrome (Selenium by default, Playwright-via-Browserless behind the `image-exporter-use-browserless` flag). It loads `{SITE_URL}/exporter?token=<15-min render JWT>` — a standalone page (`frontend/src/exporter/`) that renders the insight from data injected server-side into `window.POSTHOG_EXPORTED_DATA`, so the page makes no API calls. The exporter waits for `.ExportedInsight` to appear and `.Spinner` to disappear, measures content, resizes the window, and takes a full-window screenshot at 2x scale.

Canvas is a non-issue: the screenshot rasterizes the compositor output (canvas layers, overlays, legends) exactly as a user sees it — we never read pixels out of the canvas. This is how subscription emails/Slack digests already deliver trend/funnel chart images. Heatmaps additionally wait for a `.heatmaps-ready` class.

### Auth model (answers "but we have auth…")

- **Who pasted the link:** the unfurl handler resolves the Slack user to a PostHog user by email (`users:read.email`) and runs `UserAccessControl` checks on the resource before unfurling. No PostHog access → no unfurl.
- **How Slack fetches the image:** Slack `image` blocks are fetched by Slack's servers, unauthenticated. The existing answer is purpose-scoped JWT URLs on `ExportedAsset`: `/exporter/<filename>.png?token=<jwt>` is served sessionlessly by `SharingViewerPageViewSet`, surface-restricted by token purpose. Slack subscriptions use a 365-day `subscription_delivery` token today (`get_subscription_delivery_content_url()`).

The Slack app is already configured for this: requested scopes include `links:read`/`links:write`, and the manifest generator (`frontend/src/scenes/settings/environment/SlackIntegration.tsx`) sets `unfurl_domains` and subscribes to `link_shared`.

## Proposed change

All in `handle_posthog_link_unfurl` plus a small Celery task:

1. **Ack fast, unfurl async.** Slack wants the event ACKed in ~3s; a chart export takes longer (cache warm + browser render). `chat.unfurl` works retroactively given `channel` + `message_ts`, so return 200 immediately and dispatch a Celery task. The legacy path and subscriptions already follow this shape — `generate_assets()` in `ee/tasks/subscriptions/subscription_utils.py` is reusable nearly as-is.
2. **In the task:** after the existing access check, create an `ExportedAsset(insight=..., export_format=PNG)`, run `export_asset`, then build the unfurl payload with an added `{"type": "image", "image_url": ...}` block using a token URL.
3. **Token purpose:** mint a new, shorter-lived token purpose (e.g. `purpose="unfurl"`, days not a year) rather than reusing the 365-day subscription token. Slack caches the image after first fetch, so a short TTL costs nothing.
4. **Reuse recent assets:** if an asset for the same insight was rendered in the last few hours, reuse it instead of spinning up a new Chrome render — unfurls will fire on every paste.
5. **Fallback:** if export fails or times out, send the current text-only unfurl — strictly better than nothing, and it is what ships today.

## Open product decision

The per-user access check gates the *unfurl* on the paster's permissions, but the resulting image is then visible to the whole channel (and anyone the message is forwarded to, for the token's lifetime). That arguably matches reality (the paster could screenshot the chart anyway) and matches the subscription trust model, but it deserves a deliberate call — especially for orgs using advanced access controls on insights. Options if stricter behavior is wanted: only attach images in channels where the Slack workspace ↔ PostHog org mapping implies shared access, or make image unfurls an opt-in project setting.
