---
description: Talking to the outside world — `@posthog/http-request` is the single egress tool (authenticated, approval-gated, host-bound secrets like ${EXAMPLE_API_TOKEN}). Why egress is gated, how the allowed_hosts binding stops a leaked token going to the wrong host, and what the gate means for unattended (cron/webhook) work. Load before any http-request.
---

# Reaching the internet

`@posthog/http-request` is your one door to the outside world — reads
_and_ writes, public _and_ authenticated. (A lighter, ungated
`@posthog/web-fetch` for "just read this public page" is referenced in
the platform but **not shipped yet** — until it lands, `http-request`
covers reads too, gate and all.)

## `@posthog/http-request` — authenticated, gated ⛔

A full HTTP request with headers. Two things make it special:

1. **It's approval-gated** (`principal`). Network egress with credentials
   is exactly the kind of thing a human should see — so calling it
   queues a confirmation. Load **`working-with-approvals`** and narrate
   the wait. The gate has `allow_edit`, so the approver can tweak the
   request before it goes out.
2. **Secrets are host-bound.** You reference a token as `${EXAMPLE_API_TOKEN}`
   in a header (`Authorization: Bearer ${EXAMPLE_API_TOKEN}`). The
   platform substitutes the real value **only if the request's host is
   in that secret's `allowed_hosts`** (here, `api.example.com`). Aim
   `${EXAMPLE_API_TOKEN}` at any other host and substitution refuses with
   `secret_no_host_binding` _before the request leaves the runner_.

That binding is the safety story: even if you were steered (prompt
injection in something you read) into POSTing the token to
`evil.example`, it would never substitute. You don't have to police
this — the platform does — but know _why_ a substitution might refuse.

## Setting the token

If `${EXAMPLE_API_TOKEN}` isn't set yet, you'll see it's unavailable.
In a console session, use the `set_secret` client tool to punch out an
inline form ("I need an API token for api.example.com — here's where to
paste it"). It's `interactive`: the call parks the session and you get
the outcome on a later turn. Outside the console, point the user at
**/connections**. Never ask them to paste the token into chat.

## The gate, and unattended work

Every `http-request` is `principal`-gated — so when _you're talking to a
user_ (chat, Slack), egress is one tap: say what you're calling and why,
fire it, hand over the approval link, end your turn (load
**`working-with-approvals`**).

But in an **unattended** session (the `daily-delight` cron, a webhook)
there's no one waiting to tap approve — a gated fetch just parks. So
don't depend on a live fetch there: lean on what's already stored, or
compose from what you know, and save the live `http-request` for when a
human is in the loop to approve it. `on-this-day` is written around
exactly this.

When you do `http-request`, say what you're calling and why before you
fire it — the human approving wants context, not a bare URL.
