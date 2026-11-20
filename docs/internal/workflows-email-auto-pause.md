# Workflow email auto-pause

One workflow with a rotten list or a spammy message can poison the shared SES account every customer sends through.
An hourly detector pauses that workflow's email when its spam complaint or hard bounce rate crosses a threshold, and warns the project's admins one band earlier.
Only the workflow's email stops: in a running workflow its other steps keep running, and a transactional send to it is refused, usually with `sending_paused` (a project suspension answers `sending_suspended` first, and an async send can be refused later by the worker).
Other workflows keep sending unless they are paused too or the project's sending is suspended.
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
A warning goes out only while the rate its reason leads with, the project's for a project warning, is under the pause rate; otherwise the detector tries the next signal.
Batch job metrics count toward their parent workflow, and discovery gates sum at the team level so a breach split across many small batch jobs still surfaces.

Feedback arrives hours or days after the send it belongs to.
So a rate must also cross against the larger of two send counts: the window's own, and the sends of the equal window just before it.
Late bounces from a large send the day before then cannot pause a workflow that is quiet now, and a workflow that sends steadily keeps its full rate.
The volume gates and the reason the customer reads use the window's own sends.

The detector also judges the whole project, on hard bounces only.
When the project's unpaused workflows together pass both volume gates and a hard bounce rate, it pauses (or warns) each of them whose own rate is at that rate, even when that workflow is under the volume gates alone.
A workflow under the rate keeps sending.
The project rate's second denominator adds up what each workflow is judged on: the larger of its window's sends and its earlier window's sends when it has hard bounces in the window, and its window's sends when it has none.
A clean workflow has no late bounces in it, so its earlier sends say nothing about its siblings' bounces, and one bouncing workflow's earlier batch never stands in for its siblings' sends.
Complaints stay per workflow: a complaint says one recipient objected to one workflow's email, so a sibling's complaints are no evidence against it, and complaint feedback replayed by SES during an incident would otherwise pause every workflow in the project.
The pause reason then says the project's workflows passed the pause limit and names the workflow's sends and how many of the bounces came from it, with no project-wide figures, because people with access to only that workflow can read it. A warning email goes to the project's admins and names the project's rate, and the log and the `workflow_email_auto_pause_total` / `workflow_email_warning_total` counters carry `scope="project"`.

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

`WORKFLOW_EMAIL_AUTO_PAUSE_EXEMPT_WORKFLOW_IDS` takes a comma-separated list of workflow ids that stay in dry run while the flag is on.
The detector still logs their own breaches, with `mode="exempt"`, and writes nothing.
Their sends and feedback stay out of the project totals, so an exempt workflow cannot pause its siblings.
A project breach that only an exempt workflow's feedback would cause is neither applied nor logged.
An exempt workflow is judged on its own sends only, never on its project's.
An id that is not a UUID in the 8-4-4-4-12 form, in either case, stops Django from starting.
Use it for a workflow whose email must not stop, such as sign-in verification codes.

A workflow whose every email step is transactional (`message_category_type` is `transactional`) is never paused automatically.
Where it would be paused, the sweep sends its admins the warning email instead, at most once per warning cooldown, and logs the breach at warning level with `mode="transactional"`.
While enforcement is off, these breaches log as `mode="dry_run"` with `transactional=true`.
Its warning email says it is not paused automatically and that staff can pause it by hand.
Like an exempt workflow, it is judged on its own sends only, and its sends and feedback stay out of the project totals.
A workflow with one email step that is not transactional, such as a marketing step, is judged like any other.
The rule matches the quota check, so it reads `function_email` steps only.

Optionally add the pause metric name to `WORKFLOWS_EMAIL_TIER_AUTO_PAUSE_METRIC_NAMES` afterwards, so an auto-paused workflow also demotes its team's tier at the next daily run.

## Known limits

- Gmail runs no feedback loop, so Gmail complaints never appear in these rates; true complaint rates are higher than measured.
- The detector reads at most 48 hours back: the 24h window and the 24 hours before it. Chronic slow deterioration is the tier system's job.
- A workflow below every volume gate is auto-paused only through its project's hard bounce check; the team's tier caps bound its blast radius, and staff can pause it by hand.
- Workflow completion does not confirm an email send. Test responses expose the email provider outcome separately; a skipped send retains its reason, and provider acceptance does not confirm inbox delivery.
- Skipped sends log at error level in the run and record an `email_paused` metric; the run itself continues past the email step, so downstream steps still execute.
- Sends from the PostHog test sender (the `email_sandbox` step) never count toward a workflow's rates and are never paused by the detector. They record no ordinary email metrics, and the PostHog test sender has its own controls (see [email sending tiers](workflows-email-sending-tiers.md#posthog-test-sender)).
