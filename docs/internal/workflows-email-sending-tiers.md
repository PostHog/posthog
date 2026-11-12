# Workflow email sending tiers

Every project has a trust tier that caps how much workflow email it can send: a daily cap and a maximum batch audience.
Projects start at the lowest tier and earn higher ones by sending cleanly; dirty rates, AWS tenant reputation findings, suspensions, and long dormancy move them down.
The tiers exist because all workflow email shares one SES account whose reputation pools every project's complaints.
Only workflows that send email are subject to the tiers; SMS, push, and webhook activity is never capped by them.
Transactional email is never delayed by the send-time caps, but it is still charged against them (see Transactional email below).

## Where the pieces live

- Tier state: `email_sending_tier`, `email_sending_tier_updated_at` (dwell anchor), `email_sending_tier_demoted_at` (demotion cooldown anchor), and `email_sending_tier_pinned` on `TeamWorkflowsConfig`.
- Tier movement: a daily Celery sweep (07:15 UTC, after the SES tenant-state reconcile at 07:00) in `products/workflows/backend/services/email_sending_tier.py`.
- Batch audience cap: `get_hogflow_batch_trigger_limit` in `products/workflows/backend/utils/batch_trigger_limit.py`, applied at batch dispatch and shown in the blast radius preview.
- Send-time cap: one Valkey token bucket per team in the CDP email worker (`claimTeamSendingBudget` in `nodejs/src/cdp/services/messaging/email.service.ts`).
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

Two sides read their own env vars because the worker never reads Django settings.
Set them together; drift means the UI describes limits the worker does not apply, or the reverse.

Django (`posthog/settings/web.py`):

- `WORKFLOWS_EMAIL_TIER_MODE`: `off` (default), `shadow`, or `enforce`. Unrecognized values read as `off`.
- `WORKFLOWS_EMAIL_TIER_DAILY_CAPS`, `WORKFLOWS_EMAIL_TIER_BATCH_AUDIENCE_CAPS`: comma-separated tables indexed by tier. The shorter table decides the tier count.
- `WORKFLOWS_EMAIL_TIER_MIN_DAYS_AT_TIER`: per-tier dwell before promotion, comma-separated, clamped to the last entry.
- Promotion and demotion knobs: `WORKFLOWS_EMAIL_TIER_RATE_WINDOW_DAYS` (promotion window), `WORKFLOWS_EMAIL_TIER_DEMOTION_WINDOW_DAYS`, `WORKFLOWS_EMAIL_TIER_DEMOTION_COOLDOWN_DAYS` (keep at least as long as the demotion window), `WORKFLOWS_EMAIL_TIER_INACTIVITY_DECAY_DAYS` (0 disables decay), `WORKFLOWS_EMAIL_TIER_MIN_ACTIVE_DAYS`, `WORKFLOWS_EMAIL_TIER_MIN_DAILY_USE_RATIO`, `WORKFLOWS_EMAIL_TIER_MAX_COMPLAINT_RATE`, `WORKFLOWS_EMAIL_TIER_MAX_BOUNCE_RATE`, `WORKFLOWS_EMAIL_TIER_COMPLAINT_RATE_MIN_SENDS`, `WORKFLOWS_EMAIL_TIER_COMPLAINT_COUNT_BACKSTOP`, `WORKFLOWS_EMAIL_TIER_BOUNCE_RATE_MIN_SENDS`.
- Trusted floor: `WORKFLOWS_EMAIL_TIER_TRUSTED_FLOOR_TIER` (0 disables the floor), `WORKFLOWS_EMAIL_TIER_TRUSTED_MIN_ORG_AGE_DAYS`, `WORKFLOWS_EMAIL_TIER_TRUSTED_MIN_SCORE`.
- `HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS`: the pre-tier allowlist. It overrides the tier entirely, so a saved tier does nothing for a listed team.

Worker (`nodejs/src/cdp/config.ts`):

- `EMAIL_TEAM_SENDING_CAP_MODE`: `off` (default), `shadow`, or `enforce`.
- `EMAIL_TEAM_SENDING_CAP_DAILY_BY_TIER`: must mirror the Django table. An unusable table, such as one with a non-integer entry, falls back to the worker's built-in default table.

All of these reach production as environment variables through `posthog/charts` (with any secret values via `posthog/secrets`).
Charts sets both modes to `enforce` in every environment, so the rollout order below is complete there. The cap tables are not set there, so each side runs on its code defaults, and a change to a default table takes effect on deploy.

## Decision rules the sweep applies

In order: staff suspension or an AWS-paused tenant drops to tier 0; a dirty 7-day window, a workflow auto-pause, or a HIGH tenant reputation impact demotes one tier (at most once per cooldown, anchored on the last rate demotion); a tier above 0 with zero sends for the decay period drops one step per period; promotion needs the dwell served, real use of the tier (at least the use ratio of the daily cap on the minimum number of separate days, counted only after the tier anchor), a clean 30-day window, and a clean tenant reputation.
A trusted account skips the dwell and the use bar and moves straight to the floor, tier 3.
It qualifies when its organization has an active subscription and a Billing `workflow_emails` trust score of at least 7, is at least 90 days old, the team's rates inside the 30-day window are clean, AWS has synced its tenant as enabled with no reputation impact, and the team was never demoted, suspended by staff, or paused by AWS.
For the floor, the bounce and complaint rates count on any number of sends, because the floor skips the volume bar that otherwise backs up a small sample.
An AWS pause drops an unpinned team to tier 0 at once, as a staff suspension does.
Billing counts a free trial as an active subscription and gives it the same score as most paid plans (3), so the score bar is what keeps trials out.
An unsynced subscription (`NULL`) or a missing score does not qualify.
A qualifying team does not need to have sent anything: it gets the floor as soon as AWS reports its tenant as enabled with no reputation impact, without waiting for the daily sweep, so its first sends are not held to the tier 0 cap.
Inactivity decay stops at the floor, so a dormant trusted team keeps tier 3.
Rates only count on a meaningful denominator; below the complaint floor, the absolute complaint backstop still applies, including in windows with no sends.
Pinned teams never move automatically.

While the tier is enforced, the sweep notifies teams it moved: a rate demotion sends an in-app notification plus an email to project admins, and an earned promotion sends an in-app notification only.
Trusted floor raises, decay, suspension drops, admin recomputes, and the backfill stay silent.

## Transactional email

An email step categorized as transactional is never delayed by the send-time bucket, in any mode.
A password reset or a receipt that arrives two hours late has already failed the person waiting for it, so pacing it achieves nothing that dropping it would not.
This matches the billing quota, which transactional email already bypasses.

The send still drains the bucket by what it costs, so transactional volume displaces the project's marketing while tokens remain.
A project that spends its whole allowance on transactional email has nothing left for marketing, which is the intended trade.

The charge does not bound the exemption.
The bucket records no debt, so once a project empties it further transactional sends cost nothing and this cap stops pacing it.
A project that labels all of its email transactional is therefore not paced per team at all.
No other control bounds that volume per project either.
The SES account rate limiter, which every send still passes, paces the whole account rather than one project.
What is left is suspension, and the daily sweep demoting the project on its complaint and bounce rates after the fact.
Making the cap itself bound the case needs overdraw in the shared token bucket, which is a change to `RateLimiterService` and is not done here.

The category is self-declared in the email step, same as everywhere else it is read.
That is not a new trust boundary: the same field already exempts a send from recipient opt-outs and from the billing quota, both larger levers than pacing.

`cdp_team_email_cap_delayed_total{mode="transactional"}` counts transactional sends that a cap would have delayed.
They are kept out of `mode="shadow"` so the shadow counts stay a true forecast of what enforce would delay.
A project appearing there often is spending more on transactional than its tier allows, which is the signal to check the categorization or raise the tier.

## Sandbox sender

Sends through the sandbox sender (the `email_sandbox` step) never feed a project's tier.
They go through a separate SES tenant and configuration set and record none of `email_sent`, `email_bounced_hard` or `email_blocked`, so the sweep never sees them.
They never draw from the team bucket either.
The sandbox has its own controls: recipients limited to verified organization members, daily caps, suppression, the staff organization block in `/admin/workflows/sandboxsenderorganizationblock/`, and the SES tenant pause.

## Rollout order

1. Merge and deploy with both modes `off`. The daily sweep starts computing and storing tiers immediately.
2. Run `python manage.py backfill_workflows_email_sending_tiers` per region, read the printed distribution, then re-run with `--apply`. This lands established senders on their earned tier in one step.
3. Set both modes to `shadow` via charts. Nothing is delayed; would-be delays log and count in `cdp_team_email_cap_delayed_total{mode="shadow"}`. Watch that against real traffic.
4. Set both modes to `enforce`. Enforcement applies to every team at once; the Reputation tab's allowance card appears at this point.
   Never set the Django mode to `enforce` on a deployment whose email worker does not carry the send-time caps: the batch audience cap alone can be sidestepped by editing a workflow while a batch is queued, and the send-time bucket is what bounds that.
5. To back out, set the modes back to `off`; the tiers keep computing and nothing else changes.

## Known limits

- The batch audience cap is decided when the batch is dispatched. Adding an email step to the workflow while a batch is queued does not re-cap it; the send-time bucket still caps every email at execution. This is why enforcement requires the worker caps to be deployed (see the rollout order).
- Test-panel sends bypass the team bucket on purpose, matching the per-workflow rate limit.
- Rescheduled emails keep their email queue priority while waiting. After a team-cap, workflow-pacing, or SES-throttle retry, the workflow restores its origin queue and priority when it next leaves the email queue. A push notification retried while the workflow is on the email queue behaves the same way and waits at the priority of its own message category.
- Transactional sends are charged but never delayed, so a team whose transactional volume alone exceeds its tier can hold its own marketing at zero (see Transactional email below).
- The bucket is a token bucket: a full idle bucket plus refill allows up to roughly twice the stated cap in the very first period. The bucket TTL exceeds the refill period so this does not recur from idling.
- A denied send parks until the bucket has refilled enough to cover it, instead of retrying on a fixed few-minute cadence.
  The computed wait is capped at one hour and then jittered 1x to 2x, so a parked send can wait just under two hours between attempts.
  The wait reserves nothing: a competing send can take the tokens first, and the send parks again.
  Capacity that arrives early is only noticed when the send wakes.
  After a manual tier raise, a capped team's backlog can sit still for up to two hours.
  A send denied because the limiter itself failed keeps the token bucket cadence, at most 5 to 10 minutes.
- Gmail provides no per-message feedback loop, so complaint rates (ours and AWS's) cannot see Gmail complaints at all.
- The `HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS` allowlist elevates a team to the top tier in Django only: the UI, the admin, and the batch audience cap show top-tier numbers, but the worker's send-time bucket reads the stored tier. An allowlisted team below the top tier is therefore throttled at its stored tier while being told otherwise, and its shadow-mode delay counts overstate real impact. Before enforcing, pin each allowlisted team at the top tier from the Django admin and empty the allowlist, rather than plumbing the list into the worker.
