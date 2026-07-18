# RFC: custom SMTP provider support for workflow email sends

- **Status:** draft
- **Issue:** [#52675](https://github.com/PostHog/posthog/issues/52675)
- **Origin:** community request on [posthog.com/questions/custom-smtp-support](https://posthog.com/questions/custom-smtp-support) (multiple users asking, most recently wanting to relay through their existing email service via SMTP)

## Problem

Workflow email sends are hardcoded to PostHog-managed AWS SES. Customers who already run their own email infrastructure (their own SMTP server, or an email service that exposes SMTP relay) cannot use it. This blocks workflow adoption outright for teams that need:

- **Deliverability and reputation control** — they've spent years warming up a domain/IP with their provider and don't want to start over on a shared PostHog SES tenant.
- **Compliance** — some orgs require all outbound email to flow through approved infrastructure (archiving, DLP, regional routing).
- **Consolidation** — one provider for all product email, with its own suppression lists and analytics.

The direct quote from the original request: "We would have moved over our workflows already if this was possible."

### What actually gets the job done for customers

The minimum viable ask is small: *let me point workflow emails at my SMTP host with my credentials, sending from my address.* Customers do **not** need PostHog to manage DNS/DKIM for them in this mode — their provider already did that when they set up their domain there. They do expect:

1. Enter host, port, username, password, encryption mode, from-address, from-name.
2. A "test connection" button that proves the credentials work before they wire it into a workflow.
3. Their workflow emails go out through that relay, with the same email editor, personalization, preference/unsubscribe handling, and send metrics they'd get on the native channel.

## Current architecture (what exists today)

The email channel is already structured around a `provider` discriminator — it's just that only `ses` (and `maildev` for local dev) are allowed:

- **Integration model** — `Integration(kind="email")` with `config` (plain JSON, frontend-visible) and `sensitive_config` (`EncryptedJSONField`, never serialized to the frontend). `EmailIntegration` (`posthog/models/integration.py`) branches on `config.provider` in `create_native_integration` / `update_native_integration` / `verify` and raises on anything but `ses`/`maildev`. `NativeEmailIntegrationSerializer` (`posthog/api/integration.py`) hardcodes the same choices.
- **Provider module** — `products/workflows/backend/providers/` holds `SESProvider` (SES tenant creation, domain identity, DKIM, MAIL FROM, DNS record verification) and the maildev fixture. There's no shared provider interface yet; callers branch on the provider string.
- **Runtime delivery** — a workflow email action runs the hidden `template-email` hog function, whose `sendEmail()` call is queued onto a dedicated Cyclotron `email` queue. `EmailService.executeSendEmail` (`nodejs/src/cdp/services/messaging/email.service.ts`) loads the integration (with `sensitive_config` transparently decrypted by `IntegrationManagerService`), resolves the verified sender, then dispatches on `integration.config.provider`: `sendEmailWithSES` or `sendEmailWithMaildev` (the latter already uses `nodemailer`).
- **Engagement tracking** — opens and clicks are **PostHog-hosted**: `EmailTrackingService` injects a tracking pixel and rewrites links to a signed PostHog redirect endpoint. Delivered/bounced/complaint events, by contrast, arrive via an SES→SNS webhook (`SesWebhookHandler`) and are SES-specific.
- **Rate limiting** — the email worker queue is gated by a single global token bucket keyed `@posthog/ses/global`, protecting PostHog's shared SES sending budget.
- **Precedents** — `PostgreSQLIntegration`/`SnowflakeIntegration` already model "connection config in `config`, password in `sensitive_config`". Django's own transactional email (`posthog/email.py::_send_via_smtp`) is a battle-tested generic SMTP sender, but it's instance-wide, Python/Celery, and not connected to the workflows pipeline.

## Proposal

Add `smtp` as a third value of `Integration.config.provider` on the existing `email` kind, with a per-integration SMTP transport in the Node email worker. No new integration kind, no new queue, no changes to the email editor or workflow builder — the from-address picker, templating, preferences, suppression, and open/click tracking all keep working unchanged.

### Data model

No schema change. New shape within the existing `Integration(kind="email")` row:

```jsonc
// config (frontend-visible)
{
  "provider": "smtp",
  "email": "hello@example.com",     // from-address, same as today
  "name": "Example Team",           // from-name, same as today
  "host": "smtp.example.com",
  "port": 587,
  "encryption": "starttls",         // "starttls" | "ssl" (implicit TLS, 465) | "none" (dev only)
  "username": "apikey",
  "verified": true,                 // set by a successful connection test
  "verified_at": "..."
}
// sensitive_config (encrypted, never sent to frontend)
{ "password": "..." }
```

This mirrors the `PostgreSQLIntegration` split exactly, and the Node side needs zero plumbing: `IntegrationManagerService` already decrypts `sensitive_config` for `EmailService`.

### Backend (Django)

- New `SMTPProvider` in `products/workflows/backend/providers/smtp.py`. Unlike `SESProvider` it manages no remote state; its job is **connection verification**: connect to host:port with the requested encryption, EHLO, AUTH, and report a structured result (ok / dns-failure / connect-timeout / tls-failure / auth-rejected). Verification runs from the backend with the same egress restrictions as the runtime path (below).
- `EmailIntegration.create_native_integration` / `update_native_integration` / `verify` gain an `smtp` branch. For `smtp`, "verify" means a successful connection test, not DNS records — the response returns an empty `dnsRecords` list plus an advisory (non-blocking) SPF/DMARC lookup on the from-domain so we can warn about likely deliverability problems without owning them.
- Keep the existing guards: free/disposable from-domain block, and the cross-org domain-claim check (an SMTP integration for `example.com` should still not be creatable if another org holds a verified claim on that domain, and vice versa — otherwise SMTP becomes a way to spoof around the SES domain-claim model).
- `NativeEmailIntegrationSerializer` gains the new fields with `provider` choices `["ses", "smtp"]` (+ `maildev` in DEBUG). `mail_from_subdomain` stays SES-only.
- Password updates follow the usual write-only pattern: omitted password on PATCH means "keep existing".

### Runtime (Node email worker)

- `EmailService.executeSendEmail` gains a `sendEmailWithSMTP` branch using `nodemailer` (already a dependency via the maildev path). Transports are pooled and cached per integration id, invalidated by the existing `reload-integrations` pubsub, so a config change takes effect without restart.
- **Error semantics:** map SMTP 4xx responses and connect/socket timeouts to the existing reschedule path (same shape as `SESThrottleError` handling) with capped backoff and a max-attempt budget; map 5xx (auth failure, relay denied, mailbox rejected) to a terminal `email_failed` with the server's response in the app-metric/log so users can self-diagnose. Persistent auth failures also write to `integration.errors` so the channels UI can badge the integration as broken.
- **Rate limiting:** SMTP jobs must not consume the global SES token bucket. v1: the rate-limited queue wrapper checks the integration's provider and skips the SES bucket for `smtp`, relying on a conservative per-integration concurrency cap (small pooled connection count) plus the 4xx-reschedule behavior — the customer's relay enforces its own budget and we back off when it says so. A proper per-integration token bucket is a fast-follow (the Valkey token-bucket mechanism is reusable; only the key needs to become per-integration).
- **Metrics/tracking semantics for SMTP:**
  - `email_sent` / `email_failed` — unchanged (we know synchronously whether the relay accepted the message).
  - `email_opened` / `email_link_clicked` — unchanged, because the pixel and click redirects are PostHog-hosted.
  - `email_delivered` / `email_bounced` / `email_blocked` — **not available** for SMTP in v1 (these come from the SES webhook). The UI should show these metrics as "not supported by this provider" rather than zero. Bounce-driven auto-opt-out consequently doesn't fire for SMTP; the docs must state that suppression on hard bounces is the customer's provider's responsibility. (See open questions for a possible generic bounce webhook later.)
  - List-Unsubscribe headers, preference links, suppression-list pre-send checks, and message-asset snapshots are all provider-agnostic and stay on.

### Security

This is the riskiest part of the change: the email worker will open raw TCP connections to customer-supplied hosts.

- **SSRF/egress:** resolve the host and reject private, loopback, link-local, and cloud-metadata ranges before connecting, and pin the connection to the resolved IP (DNS-rebinding-safe), reusing the same protections as CDP's outbound fetch path. This applies to both the Django-side connection test and the Node-side send.
- **Ports:** allow only 587, 465, and 2525. Port 25 stays blocked — unauthenticated relay from PostHog Cloud IPs is a spam/abuse vector and most clouds block it anyway. Self-hosted deployments can widen this via an env allowlist.
- **TLS:** default to certificate verification on. An explicit "allow invalid certificates" escape hatch is deliberately **not** offered in v1 (it's the most-requested foot-gun in every SMTP integration; revisit only with real demand from self-hosted users).
- **Credentials:** password only ever in `sensitive_config`; never echoed to the frontend; connection-test responses must not include it in error strings.
- **Abuse:** emails still flow through PostHog's suppression and unsubscribe machinery, and the customer's own relay credentials bound the blast radius — a compromised or abusive workspace burns its own sender reputation, not PostHog's shared SES tenancy. That is strictly better for us than the status quo.

### Frontend

- `EmailSetupModal` gets a real provider choice: "PostHog-managed (recommended)" vs "Custom SMTP". The SMTP variant swaps the DNS-records table for host/port/encryption/username/password fields and a "Test connection" button (calls the existing `verify` endpoint; success sets `verified`). The SES path is untouched.
- `EmailSenderFormType.provider` union widens to `'ses' | 'smtp' | 'maildev'`; the domain-grouped channels list renders SMTP senders with a provider badge and connection-status instead of DNS status.
- The workflow email step needs no changes — verified SMTP senders appear in the existing from-address picker.

## Rollout

1. **Phase 1 (backend + runtime, flagged):** `SMTPProvider`, serializer/model branches, `sendEmailWithSMTP`, egress guards, error mapping. Gated by a `messaging-custom-smtp` feature flag. Testable end to end via the API without UI.
2. **Phase 2 (UI + docs):** setup modal, connection test UX, channels-list rendering, docs page under workflows "configure channels" covering the delivery-metrics caveat and provider-specific setup notes (e.g. providers that require the username `apikey`).
3. **Beta:** enable for the requesters on the community thread; watch `email_failed` rates, worker health (a slow customer relay must not starve the shared email queue — pooled transports with per-integration caps address this), and support volume.
4. **GA:** flag removal; changelog + response on the community question.

Fast-follows, explicitly out of v1 scope: per-integration token-bucket rate limits, a generic inbound bounce webhook, and HTTP-API providers (Resend/SendGrid/Mailgun/Postmark) — the same `provider` seam accommodates all of these later.

## Alternatives considered

- **HTTP API providers first (SendGrid/Resend/etc.) instead of raw SMTP.** Nicer failure semantics and often bounce webhooks, but every one is a separate bespoke integration, and SMTP is the lowest common denominator that covers *all* of them (every major ESP exposes an SMTP relay) plus self-hosted mail servers. SMTP first, APIs later through the same seam.
- **A generic "send email" CDP destination template** (customer pastes SMTP/API creds into a normal destination). Loses everything that makes the native channel valuable: the rich email editor, message categories/preferences, unsubscribe handling, open/click tracking, message assets. Customers asked for the native channel on their infrastructure, not a webhook.
- **Reuse the instance-level Django SMTP settings** (`posthog/email.py`). Instance-wide rather than per-team, so useless on Cloud; and it's a Python/Celery path disconnected from the CDP email worker. The design borrows its transport/retry behavior, not its wiring.
- **Bring-your-own SES credentials only.** Narrower ask than what customers stated; still excludes everyone whose provider isn't AWS.

## Open questions

1. **Generic bounce ingestion** — do we eventually offer a per-team inbound webhook (and/or plus-addressed Return-Path parsing) so SMTP senders get `email_bounced` and auto-opt-out? Proposed answer: not in v1; decide based on beta feedback.
2. **Egress IPs** — customers with firewalled relays will ask for PostHog's outbound IP ranges. Do we publish/stabilize these for the email workers?
3. **Default throughput cap per SMTP integration** — pick a conservative default (e.g. small connection pool, single-digit concurrent sends) and make it a support-adjustable limit, or expose it in the UI?
4. **Domain-claim interaction** — exact semantics when the same domain has a verified SES integration in one org and an SMTP request in another (proposal above says keep the existing exclusive claim; needs product sign-off).
