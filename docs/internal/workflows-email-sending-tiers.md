# Workflow email sending tiers

Every project has a trust tier that caps how much workflow email it can send: an hourly cap, a daily cap, and a maximum batch audience.
Projects start at the lowest tier and earn higher ones by sending cleanly; dirty rates, AWS tenant reputation findings, suspensions, and long dormancy move them down.
The tiers exist because all workflow email shares one SES account whose reputation pools every project's complaints.
Only workflows that send email are subject to the tiers; SMS, push, and webhook activity is never capped by them.

## Where the pieces live

- Tier state: `email_sending_tier`, `email_sending_tier_updated_at` (dwell anchor), `email_sending_tier_demoted_at` (demotion cooldown anchor), and `email_sending_tier_pinned` on `TeamWorkflowsConfig`.
- Tier movement: a daily Celery sweep (07:15 UTC, after the SES tenant-state reconcile at 07:00) in `products/workflows/backend/services/email_sending_tier.py`.
- Batch audience cap: `get_hogflow_batch_trigger_limit` in `products/workflows/backend/utils/batch_trigger_limit.py`, applied at batch dispatch and shown in the blast radius preview.
- Send-time caps: two Valkey token buckets per team in the CDP email worker (`claimTeamSendingBudget` in `nodejs/src/cdp/services/messaging/email.service.ts`).
- Staff controls: the team's Django admin page (view state, set/pin a tier, recompute now).
- Audit trail: every tier or pin change writes an `email_sending_tier_changed` row to the team's activity log, with the before and after values and the decision reason (`staff_set` for a tier staff set by hand). Staff rows name the acting user. Sweep and backfill rows carry a trigger with the job type and a per-run id. The rows are staff-only in the activity log (`products/workflows/backend/services/email_sending_tier_audit.py`).
- Customer surface: the Reputation tab's sending allowance card, shown only while the team is enforced.
- Agent surface: the `workflows-reputation-get` MCP tool returns the same allowance (`sending_allowance` on `GET hog_flows/reputation`), behind the same `workflows-sending-tier-requests` flag.
- Raise requests: the card's "Request a higher allowance" link opens a support ticket whose hidden context starts with `Email sending tier increase request`, followed by the project ID, tier, usage, and 30-day rates.
  Search tickets for that line to find these requests.
  The `workflows-sending-tier-requests` feature flag gates the link.
  With the flag on, when the tier sets an email batch's cap, the MCP batch tool's over-cap error points agents at the same link, so they can tell the user how to ask for more.
  Agents cannot file a request themselves.
  The link shows only to accounts that can file a support ticket: a paid or custom plan, an active support trial, or an organization in its first 3 months.

## Configuration

### Sandbox sender provisioning

The `workflows-sandbox-sender` flag enables a PostHog-managed email integration per project through `POST /api/projects/:project_id/integrations/email_sandbox_sender/`.
The endpoint requires `integration:write` and project membership. Repeated requests keep the same integration and refresh its display name from the organization name.
Set `WORKFLOWS_SANDBOX_SENDER_DOMAIN`, `SES_SANDBOX_FROM_ADDRESS`, and `SES_SANDBOX_TENANT_NAME` in Django; any empty value leaves the endpoint unavailable.
The worker sends from the same `SES_SANDBOX_FROM_ADDRESS`, so set it once for Django and the worker. The address the UI shows is then the address the worker sends from.
Workflow email steps and test sends offer it as a sender.
Users cannot edit, verify, or remove the managed integration, or register their own integration on the shared domain.
The managed integration is excluded from project SES tenant migration, identity cleanup, and the reputation page's domain breakdown.
Deploy the schema, recipient restrictions, daily caps, and tenant pause checks first. Configure the shared SES route, then enable `WORKFLOWS_SANDBOX_SENDER_ENABLED` on the worker and CDP API. Enable `workflows-sandbox-sender` last so provisioning and sender selection follow delivery readiness.
The sandbox sender is available only in workflow email steps and test sends. Broadcasts, destinations, sender rotation, custom From values, and Reply-To overrides are rejected. Unchanged stored sender settings remain editable.
Saves check the sandbox sender only while `workflows-sandbox-sender` is on for the project, so projects without the flag skip the integration lookup.

### Sending tiers

Two sides read their own env vars because the worker never reads Django settings.
Set them together; drift means the UI describes limits the worker does not apply, or the reverse.

Django (`posthog/settings/web.py`):

- `WORKFLOWS_EMAIL_TIER_MODE`: `off` (default), `shadow`, or `enforce`. Unrecognized values read as `off`.
- `WORKFLOWS_EMAIL_TIER_HOURLY_CAPS`, `WORKFLOWS_EMAIL_TIER_DAILY_CAPS`, `WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS`: comma-separated tables indexed by tier. The shortest table decides the tier count.
- `WORKFLOWS_EMAIL_TIER_MIN_DAYS_AT_TIER`: per-tier dwell before promotion, comma-separated, clamped to the last entry.
- Promotion and demotion knobs: `WORKFLOWS_EMAIL_TIER_RATE_WINDOW_DAYS` (promotion window), `WORKFLOWS_EMAIL_TIER_DEMOTION_WINDOW_DAYS`, `WORKFLOWS_EMAIL_TIER_DEMOTION_COOLDOWN_DAYS` (keep at least as long as the demotion window), `WORKFLOWS_EMAIL_TIER_INACTIVITY_DECAY_DAYS` (0 disables decay), `WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS`, `WORKFLOWS_EMAIL_TIER_MIN_DAILY_USE_RATIO`, `WORKFLOWS_EMAIL_TIER_MAX_COMPLAINT_RATE`, `WORKFLOWS_EMAIL_TIER_MAX_BOUNCE_RATE`, `WORKFLOWS_EMAIL_TIER_COMPLAINT_RATE_MIN_SENDS`, `WORKFLOWS_EMAIL_TIER_COMPLAINT_COUNT_BACKSTOP`, `WORKFLOWS_EMAIL_TIER_BOUNCE_RATE_MIN_SENDS`.
- `HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS`: the pre-tier allowlist. It overrides the tier entirely, so a saved tier does nothing for a listed team.

Worker (`nodejs/src/cdp/config.ts`):

- `EMAIL_TEAM_SENDING_CAP_MODE`: `off` (default), `shadow`, or `enforce`.
- `EMAIL_TEAM_SENDING_CAP_HOURLY_BY_TIER`, `EMAIL_TEAM_SENDING_CAP_DAILY_BY_TIER`: must mirror the Django tables. An unusable table turns the cap off rather than applying a wrong number.

All of these reach production as environment variables through `posthog/charts` (with any secret values via `posthog/secrets`).
None of them are wired there yet; the charts change is part of turning the rollout mode on, not part of merging the code.

## Decision rules the sweep applies

In order: staff suspension or an AWS-paused tenant drops to tier 0; a dirty 7-day window, a workflow auto-pause, or a HIGH tenant reputation impact demotes one tier (at most once per cooldown, anchored on the last rate demotion); a tier above 0 with zero sends for the decay period drops one step per period; promotion needs the dwell served, real use of the tier (at least the use ratio of the daily cap on the minimum number of separate days, counted only after the tier anchor), a clean 30-day window, and a clean tenant reputation.
Rates only count on a meaningful denominator; below the complaint floor, the absolute complaint backstop still applies, including in windows with no sends.
Sandbox sender sends never count as sends: the sweep subtracts `email_sandbox_sent` from `email_sent` per day, floored at zero. Their bounces and complaints still count.
Pinned teams never move automatically.

While the tier is enforced, the sweep notifies teams it moved: a rate demotion sends an in-app notification plus an email to project admins, and an earned promotion sends an in-app notification only.
Decay, suspension drops, admin recomputes, and the backfill stay silent.

## Rollout order

1. Merge and deploy with both modes `off`. The daily sweep starts computing and storing tiers immediately.
2. Run `python manage.py backfill_workflows_email_sending_tiers` per region, read the printed distribution, then re-run with `--apply`. This lands established senders on their earned tier in one step.
3. Set both modes to `shadow` via charts. Nothing is delayed; would-be delays log and count in `cdp_team_email_cap_delayed_total{mode="shadow"}`. Watch that against real traffic.
4. Set both modes to `enforce`. Enforcement applies to every team at once; the Reputation tab's allowance card appears at this point.
   Never set the Django mode to `enforce` on a deployment whose email worker does not carry the send-time caps: the batch audience cap alone can be sidestepped by editing a workflow while a batch is queued, and the send-time buckets are what bound that.
5. To back out, set the modes back to `off`; the tiers keep computing and nothing else changes.

## Known limits

- The batch audience cap is decided when the batch is dispatched. Adding an email step to the workflow while a batch is queued does not re-cap it; the send-time buckets still cap every email at execution. This is why enforcement requires the worker caps to be deployed (see the rollout order).
- Test-panel sends bypass the team buckets on purpose, matching the per-workflow rate limit.
- The buckets are token buckets: a full idle bucket plus refill allows up to roughly twice the stated cap in the very first period. The bucket TTLs exceed the refill periods so this does not recur from idling.
- A denied send parks until every short bucket has refilled enough to cover it, instead of retrying on a fixed few-minute cadence.
  The computed wait is capped at one hour and then jittered 1x to 2x, so a parked send can wait just under two hours between attempts.
  The wait reserves nothing: a competing send can take the tokens first, and the send parks again.
  Capacity that arrives early is only noticed when the send wakes.
  After a manual tier raise, a capped team's backlog can sit still for up to two hours.
  A send denied because the limiter itself failed keeps the shorter token bucket cadence, at most 5 to 10 minutes.
- Gmail provides no per-message feedback loop, so complaint rates (ours and AWS's) cannot see Gmail complaints at all.
- The `HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS` allowlist elevates a team to the top tier in Django only: the UI, the admin, and the batch audience cap show top-tier numbers, but the worker's send-time buckets read the stored tier. An allowlisted team below the top tier is therefore throttled at its stored tier while being told otherwise, and its shadow-mode delay counts overstate real impact. Before enforcing, pin each allowlisted team at the top tier from the Django admin and empty the allowlist, rather than plumbing the list into the worker.

### Sandbox delivery

The worker sends through a `sandbox` email integration only when `WORKFLOWS_SANDBOX_SENDER_ENABLED` is on and `SES_SANDBOX_TENANT_NAME`, `SES_SANDBOX_CONFIGURATION_SET`, and `SES_SANDBOX_FROM_ADDRESS` are set.
Otherwise every send through it skips with a reason in the run log and a `workflows sandbox email blocked` event with reason `switch_off`.
Every To, CC, and BCC address must belong to an active member of the team's active organization with a verified email address.
Membership snapshots expire within one minute, and the worker checks recipients again right before delivery.
A failed or stale membership check skips the send and lists the blocked addresses in the run log.
The blocked event fires at most once an hour per team, reason, and send kind (workflow or test).
A send that passes every check goes out through the fixed SES tenant, configuration set, and From address, whatever the step's custom sender and Reply-To say.
Sandbox sends skip the team's tier budget, click and open tracking, and unsubscribe headers, because they reach only members of the sending organization.
The worker parses and normalizes the HTML, then appends a footer that names the sender and the organization ID.
It overrides root clipping and visibility styles and keeps the template's typography, so malformed markup may render differently from an own-domain send.
A template whose HTML cannot keep the footer fails the send.
The visible footer is best effort across email clients and template CSS; the signed tracking header still attributes the message.
Right before delivery, every sandbox send, test sends included, claims a daily allowance per project (`WORKFLOWS_SANDBOX_DAILY_TEAM_CAP`, one token per recipient copy) and per recipient address across the organization (`WORKFLOWS_SANDBOX_DAILY_RECIPIENT_CAP`).
The allowances are token buckets that refill their capacity over 24 hours, not calendar-day counters.
A reached allowance skips the send instead of delaying it. A limiter error, or an empty or invalid cap value, skips every sandbox send.
The worker checks members after the claim and gives the claim back when that check skips the send.
An SES throttle response also gives the claim back before the delivery retry. Returns are deduplicated, and Valkey ignores a return that arrives more than five minutes after it was issued.
Test sends run inline in the CDP API, so a sandbox-enabled CDP API opens the SES Valkey pool (`SES_RATE_LIMITER_VALKEY_*`) for the allowances. Without it, every sandbox test send skips.
Every sandbox send, test sends included, skips while the shared sandbox SES tenant is paused (`DISABLED`), or when the pause state cannot be read. A tenant Django has never synced counts as open, and SES enforces its own state.
The worker checks the pause again after the daily allowance claim and gives the claim back when the pause blocks delivery.
Django mirrors the tenant named by `SES_SANDBOX_TENANT_NAME` into `SandboxSenderTenantState` from the SES tenant-state webhook and the daily reconciliation, without emailing project admins. Set the same `SES_SANDBOX_TENANT_NAME` on Django web, Celery, and the worker.
A committed state change reaches the workers through the `reload-sandbox-sender-state` message. Own-sender sends do not read this state.
Each delivered send emits a `workflows sandbox email sent` event.
Test sends never record `email_sent`, so they do not count toward the sending tier.
A successful live sandbox send records `email_sandbox_sent` next to `email_sent`, so the workflow's metrics still show it.
The sending tier subtracts `email_sandbox_sent` from `email_sent` per day, and the team's sending allowance per workflow, both floored at zero. Sandbox bounces and complaints still count.
The CDP API's SES webhook captures `workflows sandbox email delivered` for a delivery on `SES_SANDBOX_CONFIGURATION_SET`, test sends included. Without that setting on the CDP API, the event never fires.
Deploy this metric to the worker and Django before live workflow sends use the switch in production.
