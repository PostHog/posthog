# Workflow email sending tiers

Every project has a trust tier that caps how much workflow email it can send: an hourly cap, a daily cap, and a maximum batch audience.
Projects start at the lowest tier and earn higher ones by sending cleanly; dirty rates, AWS tenant reputation findings, suspensions, and long dormancy move them down.
The tiers exist because all workflow email shares one SES account whose reputation pools every project's complaints.
Only workflows that send email are subject to the tiers; SMS, push, and webhook activity is never capped by them.

## Where the pieces live

- Tier state: `email_sending_tier`, `email_sending_tier_updated_at` (dwell anchor), `email_sending_tier_demoted_at` (demotion cooldown anchor), and `email_sending_tier_pinned` on `TeamWorkflowsConfig`.
- Tier movement: a daily Celery sweep (08:30 UTC, two hours after the SES tenant-state reconcile at 06:30, which is the state it reads) in `products/workflows/backend/services/email_sending_tier.py`.
- Batch audience cap: `get_hogflow_batch_trigger_limit` in `products/workflows/backend/utils/batch_trigger_limit.py`, applied at batch dispatch and shown in the blast radius preview.
- Send-time caps: two Valkey token buckets per team in the CDP email worker (`claimTeamSendingBudget` in `nodejs/src/cdp/services/messaging/email.service.ts`).
- Staff controls: the team's Django admin page (view state, set/pin a tier, recompute now).
- Customer surface: the Reputation tab's sending allowance card, shown only while the team is enforced.

## Configuration

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
- Gmail provides no per-message feedback loop, so complaint rates (ours and AWS's) cannot see Gmail complaints at all.
- The `HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS` allowlist elevates a team to the top tier in Django only: the UI, the admin, and the batch audience cap show top-tier numbers, but the worker's send-time buckets read the stored tier. An allowlisted team below the top tier is therefore throttled at its stored tier while being told otherwise, and its shadow-mode delay counts overstate real impact. Before enforcing, pin each allowlisted team at the top tier from the Django admin and empty the allowlist, rather than plumbing the list into the worker.
