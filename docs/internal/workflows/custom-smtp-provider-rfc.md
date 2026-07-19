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

The minimum viable ask is small: _let me point workflow emails at my SMTP host with my credentials, sending from my address._ Customers do **not** need PostHog to manage DNS/DKIM for them in this mode — their provider already did that when they set up their domain there. They do expect:

1. Enter host, port, username, password, encryption mode, from-address, from-name.
2. A "test connection" button that proves the credentials work before they wire it into a workflow.
3. Their workflow emails go out through that relay, with the same email editor, personalization, preference/unsubscribe handling, and send metrics they'd get on the native channel.

## Current architecture (what exists today)

The email channel is already structured around a `provider` discriminator — it's just that only `ses` (and `maildev` for local dev) are allowed:

- **Integration model** — `Integration(kind="email")` with `config` (plain JSON, frontend-visible) and `sensitive_config` (`EncryptedJSONField`, never serialized to the frontend). `EmailIntegration` (`posthog/models/integration.py`) branches on `config.provider` in `create_native_integration` / `update_native_integration` / `verify` and raises on anything but `ses`/`maildev`. `NativeEmailIntegrationSerializer` (`posthog/api/integration.py`) hardcodes the same choices.
- **Provider module** — `products/workflows/backend/providers/` holds `SESProvider` (SES tenant creation, domain identity, DKIM, MAIL FROM, DNS record verification) and the maildev fixture. There's no shared provider interface yet; callers branch on the provider string.
- **Runtime delivery** — a workflow email action runs the hidden `template-email` hog function, whose `sendEmail()` call is queued onto a dedicated Cyclotron `email` queue. `EmailService.executeSendEmail` (`nodejs/src/cdp/services/messaging/email.service.ts`) loads the integration (with `sensitive_config` transparently decrypted by `IntegrationManagerService`), resolves the verified sender, then dispatches on `integration.config.provider`: `sendEmailWithSES` or `sendEmailWithMaildev` (the latter already uses `nodemailer`).
- **Engagement tracking** — `EmailTrackingService` injects a tracking pixel and rewrites links to a signed PostHog redirect endpoint (`/public/m/pixel` and `/public/m/redirect`, carrying a signed `ph_id` code). The endpoints are PostHog-hosted, but **in production they deliberately record nothing** — SES's engagement tracking owns open/click attribution via the SES→SNS webhook (`SesWebhookHandler`), which reads the signed code from the `X-PostHog-Tracking-Code` MIME header that SES echoes back; recording from the pixel/redirect handlers too would double-count, so direct recording is dev/test-only. Relatedly, the in-email `ph_id` omits `distinct_id` in production: the code is HMAC-signed but not encrypted (plain base64url), and in-email URLs are visible to recipients, forwards, link-scanning middleboxes, and potentially click destinations via the `Referer` header — so recipient identifiers ride only in the header carrier, which never leaves the PostHog↔SES channel. Delivered/bounced/complaint events exist only on the webhook path and are SES-specific.
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
- **Rate limiting:** ideally SMTP jobs would not consume the global SES token bucket, but the rate-limited queue wrapper gates _dequeue_, before job payloads (and thus the integration's provider) are visible — making it provider-aware means restructuring the dequeue path. v1 therefore leaves the limiter untouched: where it is configured, SMTP jobs pass through the same global bucket (conservative — it slows SMTP sends and slightly depletes the SES budget, but breaks nothing), and the real throttle for SMTP is the small pooled connection count per integration plus the 4xx-reschedule behavior — the customer's relay enforces its own budget and we back off when it says so. Provider-aware dequeue and a per-integration token bucket are a fast-follow (the Valkey token-bucket mechanism is reusable; only the key needs to become per-integration).
- **Metrics/tracking semantics for SMTP:**
  - `email_sent` / `email_failed` — unchanged (we know synchronously whether the relay accepted the message).
  - `email_opened` / `email_link_clicked` — **work via direct recording from the PostHog pixel/redirect endpoints**, which requires flipping a production behavior. Today those handlers only record in dev/test, because SES webhooks own attribution in production and recording from both would double-count. With SMTP there is no webhook, so:
    - Mint `distinct_id` into the signed `ph_id` for SMTP-provider sends (the plumbing exists: `EmailTrackingCodeSigner.generate` supports it, `parse` only trusts a `distinct_id` from a _signed_ code so forged codes can't inject engagement events, and the dev/test handlers already pass it to `trackMetric`).
    - Mint a carrier/provider flag into the signed payload (same pattern as the existing `isTest` flag) so the pixel/redirect handlers know to record directly for SMTP-origin codes and stay silent for SES-origin ones — gating on the code itself avoids an integration lookup on a hot public endpoint and keeps SES sends from double-counting.
    - Set `Referrer-Policy: no-referrer` on the redirect response — browsers apply a 3xx response's referrer policy to the follow-up request, which stops the `ph_id` (now carrying a recipient identifier) from leaking to click destinations on legacy clients; modern defaults (`strict-origin-when-cross-origin`) already strip path+query cross-origin. The pixel is low-risk either way (that request only ever goes to PostHog).
    - Length is a non-issue: `distinct_id` is capped at 200 chars, putting worst-case `ph_id` around 500 chars and the full redirect URL at several hundred plus the encoded target — far below client URL limits. The only length-capped carrier in the current system is the SES `EmailTags` 256-char cap (which is why the signed code lives in the `X-PostHog-Tracking-Code` header), and SMTP uses neither the tag nor the header for attribution.
    - Open-rate accuracy will differ from SES-attributed opens (proxy prefetchers like Apple MPP hit the pixel; the handler comment already flags UA filtering as a known gap) — acceptable for v1, worth a docs note.
  - `email_delivered` / `email_bounced` / `email_blocked` — **not available** for SMTP in v1 (these come from the SES webhook). The UI should show these metrics as "not supported by this provider" rather than zero. Bounce-driven auto-opt-out consequently doesn't fire for SMTP; the docs must state that suppression on hard bounces is the customer's provider's responsibility. (See open questions for a possible generic bounce webhook later.)
  - List-Unsubscribe headers, preference links, suppression-list pre-send checks, and message-asset snapshots are all provider-agnostic and stay on.
- **MIME encoding:** let `nodemailer` apply its default content-transfer-encoding (quoted-printable/base64 for long-lined HTML) rather than forcing `7bit`/`8bit`, so bodies containing the long tracked URLs respect SMTP's 998-char line limit (RFC 5322). This is nodemailer's default — a don't-break-it note, not work.

### Security

This is the riskiest part of the change: the email worker will open raw TCP connections to customer-supplied hosts.

- **SSRF/egress:** resolve the host and reject private, loopback, link-local, and cloud-metadata ranges before connecting, and pin the connection to the resolved IP (DNS-rebinding-safe), reusing the same protections as CDP's outbound fetch path. This applies to both the Django-side connection test and the Node-side send.
- **Ports:** allow only 587, 465, and 2525. Port 25 stays blocked — unauthenticated relay from PostHog Cloud IPs is a spam/abuse vector and most clouds block it anyway. Self-hosted deployments can widen this via an env allowlist.
- **TLS:** default to certificate verification on. An explicit "allow invalid certificates" escape hatch is deliberately **not** offered in v1 (it's the most-requested foot-gun in every SMTP integration; revisit only with real demand from self-hosted users).
- **Credentials:** password only ever in `sensitive_config`; never echoed to the frontend; connection-test responses must not include it in error strings.
- **Recipient identifiers in tracking URLs:** SMTP sends put `distinct_id` into the in-email `ph_id` (see metrics section), which is signed but not encrypted — anyone holding the email can base64-decode it. Mitigations: the redirect response's `Referrer-Policy: no-referrer` header keeps it away from click destinations, and the HMAC prevents forgery. Whether to go further and encrypt the payload is an open question below.
- **Abuse:** emails still flow through PostHog's suppression and unsubscribe machinery, and the customer's own relay credentials bound the blast radius — a compromised or abusive workspace burns its own sender reputation, not PostHog's shared SES tenancy. That is strictly better for us than the status quo.

### Frontend

- `EmailSetupModal` gets a real provider choice: "PostHog-managed (recommended)" vs "Custom SMTP". The SMTP variant swaps the DNS-records table for host/port/encryption/username/password fields and a "Test connection" button (calls the existing `verify` endpoint; success sets `verified`). The SES path is untouched.
- `EmailSenderFormType.provider` union widens to `'ses' | 'smtp' | 'maildev'`; the domain-grouped channels list renders SMTP senders with a provider badge and connection-status instead of DNS status.
- The workflow email step needs no changes — verified SMTP senders appear in the existing from-address picker.

## Details v1 must get right

Smaller than the sections above, but each is a foreseeable failure mode or support generator if skipped:

- **Duplicate sends on ambiguous failures.** SMTP is at-least-once under retries: a socket timeout _after_ the `DATA` phase was accepted looks like a failure to us but the relay may already be delivering. Retrying it double-sends. The retry policy must distinguish pre-`DATA` failures (safe to retry) from ambiguous post-`DATA` timeouts (do not auto-retry; fail with a clear "may have been delivered" log). SES's API semantics shield us from this today; raw SMTP doesn't.
- **Inline test sends.** The editor's "Run test" bypasses the email queue and sends synchronously (`sendEmailsInline` in `hog-executor.service.ts`). A slow or black-holing customer relay would hang that inline path, so SMTP needs a tight per-send timeout (a few seconds) on the test path specifically, with the relay's response surfaced verbatim in the test panel.
- **Connection test ≠ the relay will accept your mail.** AUTH succeeding doesn't mean the relay will accept the configured from-address (most ESP relays only relay for verified identities), and won't catch sender-domain policy failures. The verify flow should therefore offer an actual **"send a test email to yourself"** step after the connection test — that's the real proof, and it exercises the exact production path.
- **Relay connection caps vs our worker fleet.** Pooled transports are per worker process; N processes × pool size can exceed a provider's per-account concurrent-connection cap (commonly ~10). Default pool size must be small (1-2 per process) and the docs should say how the effective ceiling scales; a global per-integration concurrency limit is part of the rate-limiting fast-follow.
- **Envelope sender and Message-ID.** Decide what we set as the SMTP envelope `MAIL FROM` (Return-Path) — nodemailer defaults it to the header from-address, which is right for most relays, but it's where out-of-band bounces go, so it must be documented (bounces land in the customer's mailbox/provider, not PostHog). Message-ID should be left to the relay or minted on the sender's domain, never a posthog.com domain.
- **Credential/sender UX shape.** Email integrations are one row per sender (from-address). Naively, SMTP makes users re-enter host/credentials for every sender on the same relay. v1 should at least prefill from an existing same-domain SMTP integration; a shared "SMTP connection" referenced by multiple senders is the cleaner shape but touches the integration model — decide before GA, since it's painful to restructure after.
- **Tracking-redirect hardening as a prerequisite.** Before SMTP ships, the public click-redirect endpoint must require a valid signed `ph_id` and bind the `target` URL into the signed payload. Today the redirect only checks that `target` is present, which is tolerable while all mail flows through our SES tenancy but not once arbitrary relays send mail carrying PostHog-domain redirect links — our tracking domain's URL reputation becomes an abuse target (phishing links laundered through our redirect).
- **Ops separation.** A customer's broken relay must look like _their_ integration error (badge in channels UI, app metrics, logs), never like our on-call's problem. Per-provider dashboards and alert routing on the email worker need to exclude `smtp` failures from PostHog-infra alerting while still counting them in customer-facing metrics.
- **Provider switching.** `update_native_integration` should support switching an existing sender between `ses` and `smtp` in place (re-verify required), so workflows referencing the integration id don't need rewiring — important for the "migrate off SES gradually" and "SES as fallback" stories.
- **Self-hosted unlock (bonus).** Self-hosted deployments can't realistically use the workflow email channel today (it assumes PostHog's SES tenancy). SMTP makes the channel viable for them — worth calling out in the launch, with the caveat that the email worker's boot-time signing-key guard (`ENCRYPTION_SALT_KEYS`) applies.
- **Non-ASCII addresses.** Internationalized recipient addresses need `SMTPUTF8`; not all relays support it. Treat the relay's rejection as a terminal per-recipient failure with a clear message rather than a retry.
- **AUP still applies.** Sending through customer relays doesn't exempt workflow email from PostHog's acceptable-use policy — suppression, unsubscribe, and the abuse-report path stay mandatory regardless of provider.

## Pricing

**No billing changes needed, and the price stays the same in v1.** Workflow email billing is already provider-agnostic: each email action pushes a `billable_invocation` app metric (`metric_kind: 'email'`) from the hogflow action executor (`nodejs/src/cdp/services/hogflows/billing-utils.ts`), and the usage report sums those from ClickHouse (`workflow_emails_sent_in_period`). The meter counts "email action ran", not "SES API called" — SMTP sends bill identically with zero changes, and quota/rate limiting (keyed off `BILLABLE_ACTION_TYPES`) is likewise unaffected.

Should BYO-SMTP cost less? Proposed answer: no, for v1.

- The per-email upcharge over plain function invocations overwhelmingly pays for the feature set (editor, personalization, preferences/unsubscribe machinery, tracking, message assets, metrics) — all of which SMTP customers keep consuming. The delivery cost we shed is on the order of cents per thousand.
- Our marginal cost and risk actually drop (no SES fees, customer's relay carries reputation), so flat pricing on lower cost is healthy, and the customers asking for this are blocked on infrastructure, not delivery price.
- Differentiated pricing needs a provider dimension in the meter (new `metric_kind`, new usage-report query, new billing SKU, and the action executor resolving the integration's provider at bill time). If a BYO discount ever becomes a sales objection, that change is small and forward-only — defer it.

One decision to make explicitly during implementation: whether a **terminally failed** SMTP send (bad credentials, relay rejection) bills. The billable metric is pushed at action invocation; match whatever the SES failure path does today, and if that turns out to be "failures bill", fix it for both providers rather than special-casing SMTP.

## Rollout

1. **Phase 1 (backend + runtime, flagged):** `SMTPProvider`, serializer/model branches, `sendEmailWithSMTP`, egress guards, error mapping. Gated by a `messaging-custom-smtp` feature flag. Testable end to end via the API without UI.
2. **Phase 2 (UI + docs):** setup modal, connection test UX, channels-list rendering, docs page under workflows "configure channels" covering the delivery-metrics caveat and provider-specific setup notes (e.g. providers that require the username `apikey`).
3. **Beta:** enable for the requesters on the community thread; watch `email_failed` rates, worker health (a slow customer relay must not starve the shared email queue — pooled transports with per-integration caps address this), and support volume.
4. **GA:** flag removal; changelog + response on the community question.

Fast-follows, explicitly out of v1 scope: per-integration token-bucket rate limits, a generic inbound bounce webhook, and HTTP-API providers (Resend/SendGrid/Mailgun/Postmark) — the same `provider` seam accommodates all of these later.

## Alternatives considered

- **HTTP API providers first (SendGrid/Resend/etc.) instead of raw SMTP.** Nicer failure semantics and often bounce webhooks, but every one is a separate bespoke integration, and SMTP is the lowest common denominator that covers _all_ of them (every major ESP exposes an SMTP relay) plus self-hosted mail servers. SMTP first, APIs later through the same seam.
- **A generic "send email" CDP destination template** (customer pastes SMTP/API creds into a normal destination). Loses everything that makes the native channel valuable: the rich email editor, message categories/preferences, unsubscribe handling, open/click tracking, message assets. Customers asked for the native channel on their infrastructure, not a webhook.
- **Reuse the instance-level Django SMTP settings** (`posthog/email.py`). Instance-wide rather than per-team, so useless on Cloud; and it's a Python/Celery path disconnected from the CDP email worker. The design borrows its transport/retry behavior, not its wiring.
- **Bring-your-own SES credentials only.** Narrower ask than what customers stated; still excludes everyone whose provider isn't AWS.

## Open questions

1. **Generic bounce ingestion** — do we eventually offer a per-team inbound webhook (and/or plus-addressed Return-Path parsing) so SMTP senders get `email_bounced` and auto-opt-out? Proposed answer: not in v1; decide based on beta feedback.
2. **Egress IPs** — customers with firewalled relays will ask for PostHog's outbound IP ranges. Do we publish/stabilize these for the email workers?
3. **Default throughput cap per SMTP integration** — pick a conservative default (e.g. small connection pool, single-digit concurrent sends) and make it a support-adjustable limit, or expose it in the UI?
4. **Domain-claim interaction** — exact semantics when the same domain has a verified SES integration in one org and an SMTP request in another (proposal above says keep the existing exclusive claim; needs product sign-off).
5. **Encrypt the `ph_id` payload instead of signing only?** With SMTP putting `distinct_id` in in-email URLs, the code becomes recipient PII readable by anyone holding the email (forwards, scanners). The Fernet machinery (`EncryptedFields`, same `ENCRYPTION_SALT_KEYS`) already exists on both the Django and Node sides, so encrypting is feasible — but it adds payload size and a decrypt on a hot public endpoint, and the Referer mitigation covers the main exfil path. Proposed answer: signing + `no-referrer` for v1, revisit if beta customers' distinct_ids are commonly emails.
6. **Shared SMTP connection vs per-sender credentials** — is prefill-from-same-domain good enough for v1, or do we restructure to a connection object referenced by multiple senders before GA? (See "Details v1 must get right".)
7. **Scope of surfaces** — anything that sends through the `template-email` function and an email integration (workflow steps, broadcasts, editor test sends) inherits the provider automatically since dispatch happens on `integration.config.provider`. Confirm no email surface bypasses `EmailService` before promising "all email features work with SMTP".
