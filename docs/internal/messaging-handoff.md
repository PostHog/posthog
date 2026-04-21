# Messaging infrastructure handoff

Context I want to share with the team before I leave.
Covers email (SES), push (FCM/APNS), and the React email editor work.

Flagging up front: observability and alerting are the weakest part of this stack.
Most of what's below under "alerts" is what _should_ exist, not what does.

## Email delivery (AWS SES)

### How sending works today

We have two sending paths, selected at runtime inside `_send_email()`:

- **Customer.io HTTP API** — the primary path for most transactional templates.
  Template IDs are mapped in `CUSTOMER_IO_TEMPLATE_ID_MAP`
  in `posthog/tasks/email.py` (~line 89).
- **SMTP / SES** — the fallback path, used when Customer.io isn't available
  or for emails that aren't in the template map.
  The SMTP credentials are set via the `EMAIL_HOST` dynamic settings
  (see `posthog/settings/dynamic_settings.py` lines 76–122).

Everything funnels through `posthog/email.py` and is dispatched on the
`CeleryQueue.EMAIL` queue with up to 3 retries and exponential backoff.

Domain verification / DKIM / SPF / DMARC / MAIL FROM / SES v2 tenants are all
handled by `SESProvider` in
`products/workflows/backend/providers/ses.py`.
Each team gets its own SES v2 tenant named `team-{team_id}`.
There's a migration command at
`posthog/management/commands/migrate_ses_tenants.py` for moving
pre-tenant identities over — use `--dry-run` first.

Inbound email (for Conversations) is **Mailgun**, not SES.
See `products/conversations/backend/mailgun.py`.
Don't get these mixed up — SES is outbound only, Mailgun is inbound only.

### AWS console access

- Region: `us-east-1` by default (overridable via `SES_REGION` env var).
- Credentials come from `SES_ACCESS_KEY_ID` / `SES_SECRET_ACCESS_KEY`.
  The IAM user backing these lives in the main PostHog AWS account —
  ask infra for console access if you don't have it yet.
- Things you'll want to check regularly in the SES console:
  - **Reputation dashboard** — bounce rate and complaint rate.
    SES will throttle or pause sending if bounce rate >5% or complaint >0.1%.
  - **Sending statistics** — daily send volume vs. quota.
  - **Suppression list** — addresses SES refuses to deliver to.
  - **Configuration sets** — we don't use these heavily yet but they're where
    per-message event publishing to SNS/CloudWatch would be configured.

### Grafana / observability

**This is the biggest gap.** We don't have meaningful email metrics today.
`MessagingRecord` (`posthog/models/messaging.py`) tracks _what we sent_
for dedup purposes, but nothing tracks _what was delivered_.

What exists:

- PostHog `posthoganalytics.capture` calls for
  `"transactional email triggered"`, `"verification email sent"`, etc.
  These land in the internal PostHog project, not Grafana.
- A single Prometheus counter — `integration_oauth_refresh` — which isn't
  email-specific but does tell you if the SES IAM token refresh is failing.

What's missing (rough priority order):

1. A Prometheus counter for emails sent, labelled by template + backend
   (customerio vs smtp).
2. A bounce/complaint rate pull from SES into Grafana — either via
   CloudWatch → Prometheus or via a periodic Celery task that hits
   `GetSendStatistics`.
3. Retry/failure counters on the Celery send task.
4. Suppression list growth rate.

### Alerts

Existing email-adjacent alerts (all internal PostHog features, not ops alerts):

- Plugin disabled → `send_fatal_plugin_error`
- HogFunction disabled → `send_hog_function_disabled`
- Batch export failure → `send_batch_export_run_failure`
- Materialized view failure digest → `send_matview_failure_digest`
- Weekly error tracking digest → `send_error_tracking_weekly_digest`

None of these alert on the _email system itself_. Missing:

- **Bounce rate > 3%** (SES pauses at 5%, we should know before then)
- **Complaint rate > 0.05%** (SES pauses at 0.1%)
- **SES sending quota utilization > 80%**
- **Customer.io API failures spiking** (5xx rate, auth errors)
- **Celery email queue backlog** — the queue exists but nothing alerts on depth

The fastest way to get the first two is a periodic Celery task pulling
`GetSendStatistics` from SES and pushing a gauge to Prometheus,
then a Grafana alert rule on the gauge. That's maybe a day of work.

### Local testing

Default local setup uses **maildev** (see `docker-compose.dev.yml` lines 454–460).
It's an SMTP sink at port 1025 with a web UI at `http://localhost:1080`.

The _non-maildev_ path — what you want if you're testing the SES-specific code
like domain verification, DKIM record generation, or tenant creation —
uses **LocalStack**. When `DEBUG=True` or `TEST=True`, `posthog/settings/ses.py`
points the SES client at `http://localhost:4566` (LocalStack's default endpoint).

The DNS verification flow in `SESProvider` doesn't work against LocalStack
out of the box because LocalStack doesn't serve real DNS.
The workaround is `products/workflows/backend/providers/maildev.py`, which
returns mocked verification tokens, DKIM CNAMEs, SPF, DMARC, and MAIL FROM
records so the verification flow thinks everything's valid.

Minimum to run SES code locally without maildev SMTP:

1. `docker run -p 4566:4566 localstack/localstack`
2. Set `SES_REGION=us-east-1`, dummy access keys (LocalStack doesn't check them).
3. Import `maildev.py`'s mocked DNS records in your test setup,
   or pre-seed SES identities via awslocal:
   `awslocal ses verify-domain-identity --domain example.com`.
4. If you're testing SES v2 tenants, note LocalStack's SES v2 support is
   incomplete — `create_tenant` works but `create_tenant_resource_association`
   sometimes silently no-ops. The tests in
   `products/workflows/backend/test/test_ses_provider.py` mostly mock at
   boto3 level rather than hitting LocalStack, which is usually what you want.

## Push notifications

### FCM (Android)

Set up via the `firebase` integration kind
(`posthog/models/integration.py` lines 1467–1549, `FirebaseIntegration`).
Users upload a Google service account JSON via `POST /api/integrations/`
and it's stored encrypted in `Integration.sensitive_config["key_info"]`.

The scope we request is `https://www.googleapis.com/auth/firebase.messaging`.
Access tokens are refreshed automatically by
`posthog/tasks/integrations.py::refresh_integrations` —
it runs periodically, checks `access_token_expired()`, and refreshes at
half-TTL.

Actual push sending happens in the CDP via the Hog function at
`nodejs/src/cdp/templates/_destinations/firebase_push/firebase_push.template.ts`.
It POSTs to `https://fcm.googleapis.com/v1/projects/{projectId}/messages:send`
with the integration's current access token. Each Hog invocation = one message.
Inputs are: FCM token, title, body, and an optional data payload.

### APNS (iOS)

**Not implemented.** There is no APNS code in the repo — no `apns2`,
no `aioapns`, no `.p8` key handling, no iOS-specific integration kind.
The only iOS-push path today is via the third-party OneSignal destination at
`posthog/cdp/templates/onesignal/template_onesignal.py`, which abstracts APNS
away from us.

If/when we want native APNS, the rough shape would be a new `ApnsIntegration`
alongside `FirebaseIntegration` storing the `.p8` key + team ID + key ID +
bundle ID, a JWT-based auth helper, and a `apns_push` Hog function template.
Similar surface area to what's there for Firebase.

### Grafana / observability

Same story as email — nothing push-specific today.

What exists:

- `integration_oauth_refresh` counter (labelled by `kind` and `result`) — this
  does capture Firebase token refresh outcomes, so it's the one metric we have.
- Error strings are persisted on `Integration.errors` when refresh fails.
- The Hog function template has optional `debug` inputs that log
  request/response payloads.

What's missing:

- Counter for pushes sent, labelled by platform + success/failure.
- Counter for invalid-token errors (FCM returns `UNREGISTERED` /
  `INVALID_ARGUMENT` — these signal the user uninstalled the app).
- Rate-limit / 429 detection from FCM.
- Delivery latency histogram.

### Alerts

None. Nothing alerts on Firebase token refresh failures, nothing alerts on
FCM 4xx/5xx spikes, nothing alerts on quota.

Highest-value ones to add first:

1. **Firebase token refresh failure rate > 5% over 15min** — catches rotated
   or revoked service account keys.
2. **FCM 4xx rate spike** — usually means we're sending to stale tokens,
   which is a correctness problem.
3. **FCM 5xx / network errors** — Firebase outage or our egress problem.

### Local testing

No real local story for push today. Firebase doesn't have a sandbox — you hit
real FCM or nothing. What we do in practice:

- **Unit tests mock at the HTTP layer.** The Hog function template is tested
  by stubbing `fetch`.
- **For end-to-end testing**, you need a real Firebase project and a real
  device token. The easiest option is to create a throwaway Firebase project,
  register a test device, and hardcode its token into the function input.
- The template supports a `debug` input that logs request + response to
  Hog's console — turn this on locally to see what's being sent.

APNS does have a sandbox (`api.sandbox.push.apple.com`) — if we ever
implement APNS, we should wire that in from day one.

## React email editor

WIP on [#55521](https://github.com/PostHog/posthog/pull/55521).
This is a visual drag-and-drop email editor using the
[`react-email-editor`](https://github.com/unlayer/react-email-editor)
library (Unlayer under the hood).

### Where it lives

- **Component**: `frontend/src/scenes/hog-functions/email-templater/EmailTemplater.tsx`
  (~800 lines — the main React component)
- **State**: `emailTemplaterLogic.tsx` next to it — kea logic for form state,
  merging tags, saving, template loading.
- **Custom Unlayer tool**: `custom-tools/unsubscribeLinkTool.tsx` — adds an
  "insert unsubscribe link" button into the Unlayer toolbar.
- **Backend model**: `products/messaging/backend/models/message_template.py`
  (`MessageTemplate`) — stores the Unlayer design JSON, the rendered HTML,
  plain-text fallback, and the templating engine (Hog or Liquid).

### Where it's used

Two entry points today:

- `CyclotronJobInputs.tsx` — for CDP/workflow function inputs that want an
  email body.
- `products/workflows/frontend/TemplateLibrary/MessageTemplate.tsx` — for
  managing the reusable template library.

### Modes

There are three editor modes, selected by `type`:

| Type                    | Fields                         | Use case          |
| ----------------------- | ------------------------------ | ----------------- |
| `email`                 | from, to, subject              | Basic             |
| `native_email`          | + reply-to, cc, bcc, preheader | Full              |
| `native_email_template` | subject, preheader only        | Library templates |

### Where to pick up

Main loose ends when I last looked:

- **`TODO: Remove this default later`** in `EmailTemplater.tsx` ~line 238 —
  there's a hardcoded `default@example.com` sender that needs to become
  a real verified-sender picker backed by the SES domain identities.
- **Sender name field** is commented out with a TODO on the next line.
- **Provider selection** in `EmailSetupModal.tsx` is feature-flagged
  (`messaging-ses`) and only exposes AWS SES + maildev. This is temporary
  until we decide the non-SES story.
- The Unlayer project ID (`275430`) is currently read from preflight —
  we should double-check that's our project and not a shared/debug one
  before we ship to cloud.
- Merge tags come from `api.propertyDefinitions.list()`, which means the
  editor only knows about tracked person properties.
  Special synthetic tags today: `{{unsubscribe_url}}`,
  `{{unsubscribe_url_one_click}}`. Any new synthetic tag needs to be added
  in `emailTemplaterLogic.tsx`'s merge tag builder.

Tests exist for the advanced-field reveal/hide behavior
(`emailTemplaterLogic.test.ts`). The editor itself isn't unit-tested
because Unlayer mounts a cross-origin iframe — use Storybook or manual
testing for visual work.
