# Workflow email auto-pause

One workflow with a rotten list or a spammy message can poison the shared SES account every customer sends through.
An hourly detector pauses that workflow's email when its spam complaint or hard bounce rate crosses a threshold, and warns the project's admins one band earlier.
Only the workflow's email stops: its other steps keep running, and every other workflow keeps sending.
This complements the [email sending tiers](workflows-email-sending-tiers.md): the detector handles the acute per-workflow case in hours, the tiers handle chronic per-team trust in days.

## Where the pieces live

- Pause state: `email_sending_paused_at`, `email_sending_paused_reason`, `email_sending_paused_by` ("auto" or "staff"), `email_sending_resumed_at`, and `email_sending_warned_at` on `HogFlow`.
- Detection: an hourly Celery task (minute 35, LONG_RUNNING queue) in `products/workflows/backend/services/workflow_email_health.py`.
- Enforcement: the email worker skips sends for a paused workflow at the send choke point (`executeSendEmail` in `nodejs/src/cdp/services/messaging/email.service.ts`), reacting to a pause within seconds via config reload.
- Staff controls: pause and resume bulk actions on `/admin/workflows/hogflow/`, recorded in the object's admin history.
- Customer surface: a banner on the workflow page with the reason, and a resume button for automatic pauses. Staff pauses point to support instead.

## Thresholds

Rates are judged over whole clock hours only, because the metrics table collapses rows per hour.
The current partial hour is excluded, which adds up to an hour of detection lag on top of the hourly cadence.

| Signal          | Window | Warn at | Pause at | Needs sends | Needs events |
| --------------- | ------ | ------- | -------- | ----------- | ------------ |
| Spam complaints | 1h     | 0.5%    | 1%       | 200         | 5            |
| Spam complaints | 24h    | 0.15%   | 0.3%     | 1,000       | 10           |
| Hard bounces    | 1h     | 5%      | 10%      | 200         | 20           |
| Hard bounces    | 24h    | 2.5%    | 5%       | 1,000       | 50           |

Any one row firing is enough; both volume gates must pass before the rate counts.
Every number is a `WORKFLOW_EMAIL_AUTO_PAUSE_*` or `WORKFLOW_EMAIL_WARN_*` setting in `posthog/settings/ses.py` with an env override.
Warnings repeat at most once per `WORKFLOW_EMAIL_WARN_COOLDOWN_DAYS` (default 7) per workflow.
Batch job metrics count toward their parent workflow, and discovery gates sum at the team level so a breach split across many small batch jobs still surfaces.

## Who pauses, who resumes

- The detector pauses with `paused_by="auto"`. The customer resumes from the workflow page; project admins get an email naming the reason.
- Staff pause from Django admin with `paused_by="staff"`. Only staff can resume those: the customer's resume endpoint refuses with a contact-support message, the banner shows no button, and the email says to contact support.
- Resuming stamps `email_sending_resumed_at`, and every detector window then starts at the first full hour after it. A workflow that keeps misbehaving re-trips within a couple of hours on fresh feedback only; resuming without fixing anything cannot outrun the detector.

## Rollout

`WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED` (default off) gates every automatic write; warnings and pauses arm together.
Staff admin actions write regardless of the flag, which is the intended dogfood path before enabling.

1. Deploy dark. The detector logs `would_pause_workflow_email_sending` and `would_warn_workflow_email_sending` (with workflow name, rates, and volume) and counts `workflow_email_auto_pause_total` / `workflow_email_warning_total` with `mode="dry_run"`.
2. Read the would-pause list for a week or two and tune thresholds per region if needed.
3. Validate the machinery with one staff pause on an internal workflow: worker skip, admin email, banner, resume.
4. Set `WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED=true` per region via `posthog/charts`.
5. To back out, unset the flag; existing pauses stay until resumed.

Optionally add the pause metric name to `WORKFLOWS_EMAIL_TIER_AUTO_PAUSE_METRIC_NAMES` afterwards, so an auto-paused workflow also demotes its team's tier at the next daily run.

## Known limits

- Gmail runs no feedback loop, so Gmail complaints never appear in these rates; true complaint rates are higher than measured.
- The detector reads at most 24 hours back. Chronic slow deterioration is the tier system's job.
- A workflow below every volume gate is never auto-paused, whatever its rates; the team's tier caps bound its blast radius, and staff can pause it by hand.
- Skipped sends log at error level in the run and record an `email_paused` metric; the run itself continues past the email step, so downstream steps still execute.
