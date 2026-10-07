# Report completion and late PR attachments

A report completes after all linked implementation PRs are closed or merged.
At least one merged PR resolves the report; otherwise all closed PRs suppress it.

With the organization-level `signals-report-monitoring` flag enabled, at least one merged PR instead
puts the report in `monitoring`: implementation is complete, but the outcome is still being verified.
The state API and the **Fix implemented** action also support fixes without a pull request, after any
linked pull requests have merged or closed. Entry records `monitoring_started_at` and starts follow-up
checks' soak and measurement windows. Repeated merge notifications do not reset this timestamp.
The flag only controls new entry. Disabling it leaves existing monitoring reports visible and their
checks running. Historical resolved reports are unchanged. Keep the flag off until Django and workers
have fully deployed support for this state; local DEBUG environments enable it for development.
List and detail serialization evaluate this flag locally and fail closed while its definition is
unavailable. Configure the rollout with organization ID conditions or percentage rollouts; the local
evaluation supplies only the organization's ID. State transitions retain remote evaluation fallback.

A monitoring report automatically resolves once every applicable, non-cancelled check passes all its
remaining runs. Failed, errored, inconclusive, expired, or partially completed checks leave the report
in monitoring for review. Approval is a quality signal and does not gate verification. A report without
checks needs explicit resolution. Failures during monitoring stay on that report rather than creating
a follow-up report. New signals continue to attach without restarting implementation.
The `verifying` inbox view displays monitoring reports; the existing `monitoring` view still means PR
review. The legacy `inbox` view includes both reports awaiting a decision and monitoring reports.

The follow-up timing descriptions below also apply to monitoring: its entry replaces resolution as the
measurement anchor. Resolving a monitoring report keeps the anchor. Reopening immediately parks active
checks and clears it; the next implementation starts a new window, and stale results cannot settle it.
Archiving pauses checks and clears the anchor, including after manual resolution of a monitoring report.
Restoring starts a fresh window; restoring monitoring works even if the rollout
flag is disabled. Checks from earlier windows cannot confirm the restored report's outcome.
The open Monitoring detail refreshes its report, checks, and work log every 30 seconds, pauses in hidden
tabs, and backs off failed refreshes. Leaving Monitoring refreshes the final check results. Existing
saved default inbox filters gain Verifying once; custom selections and shared links remain authoritative.
Refund dialog copy uses the first billable PR's merge state, matching the refund endpoint, rather than
the presence of any merged PR on the report. A refunded unmerged PR archives the report and parks checks.

Attaching a new open, draft, or unknown PR to a monitoring or resolved report returns it to ready.
The shared PR-linking service applies this rule to task outputs and agent attachments.
An existing attachment retry does not reopen a report, and importing legacy assignments preserves its status.
Suppressed reports remain suppressed when another PR is attached.

A report that is `part_of` another report is a step in a plan, and the plan completes from its steps.
When every live step of a plan is closed, the plan takes their verdict: resolved if at least one step resolved, suppressed if they all were.
A plan with any step still open is left alone, and a deleted step counts neither way.
Reopening a step does not reopen a completed plan.
Deleting a step also checks the plan again.
A plan that becomes ready checks its own steps, in case they closed while the plan was still in research.
The check locks each plan before it reads and updates its state.
It continues through an already closed plan to check that plan's parent.
An archived step never undoes a resolved plan.
The roll-up runs on the step's own status change, so a merged PR, a manual resolve, a bulk state change, and an MCP state write all reach it.
A `part_of` link written on a step that already closed runs the check as well, because that write changes no status.
It continues up a plan of plans, and skips a plan that is waiting on a replacement.
It also skips a plan that carries its own open, draft, or unknown PR, because that plan's own work decides its status.
A monitoring step keeps its plan open. With monitoring enabled, a plan whose steps are resolved starts
its own pending checks in monitoring and waits for their verdicts before resolving.

## Follow-up checks

Research writes measurable outcome goals as `metric_threshold` report checks and investigative goals as `agent` checks. A metric check stores a bounded live query, baseline, comparison, and soak window; the query and display format are copied from its report metric when it names one. The check waits for the report to resolve, then the coordinator runs it and records a verdict. Metric checks keep the configured soak separate from their query window and wait until that full window contains only post-resolution data. Each run pins absolute query bounds to avoid reusing a pre-resolution cached result. Reopening clears the measurement start; the next resolution starts it again. Existing active metric checks without a recorded start begin their window at the first coordinator tick. New metric checks validate count, rate, duration, baseline, and threshold values using the same rules as report metrics; existing configurations remain readable. A later research pass reviews every open check, preserves unchanged checks and their approvals, replaces changed checks, and retires omitted checks. A failed verification turn leaves existing checks alone. Verification can revise only Expected impact; other summary sections and their chart links must remain intact. The full replacement schedule, including its soak and measurement window, must finish before the 90-day horizon. The Follow-up checks sidebar shows schedules and results for both kinds. The Expected impact section uses the same metric checks to show goals and charts, behind the person-level `signals-expected-impact` display flag. A person can mark those measurements "Looks good" as a quality signal; approval does not control scheduling or execution. The "Suggest different metrics" action starts a discussion that can atomically replace relevant open metric checks while preserving unrelated checks. A failed replacement leaves the original running, and a successful replacement starts unapproved. Report observation metrics remain separate from these forward-looking checks.

Reports awaiting human input also retain their generated checks, pending resolution. Pending sidebar rows show the minimum wait after resolution. Metric replacements require access to the query they schedule and preserve the remaining recurring runs and soak duration, including zero minutes. Replacement cannot override the soak. Creation and replacement share full schedule validation against the 90-day horizon. A replacement rejects a check moved by a concurrent report merge; reload the report and retry on the survivor. Units cannot contain null characters or unpaired Unicode surrogates. The Expected impact section shows finished verdicts and refreshes after agent tasks change checks.

The `inbox-report-checks-replace` MCP tool requires `task:write` and `query:read`. Query-specific event, action, and cohort permissions still apply. The `signals-report-checks-replace` rollout flag hides the tool unless enabled. Keep it disabled until the replacement API is deployed in every region. This gate is separate from the Expected impact display flag.

Approval advances the check's update timestamp so older list responses cannot undo it on screen. Retries preserve the original approval and timestamp. Research captures the open checks' versions before starting. If any check changes before its result is stored, that pass leaves the checks alone. A subsequent pass that sees the current checks can revise or retire them, including approved checks. Older activity results without this snapshot preserve person-selected and approved checks.

Custom HogQL aggregations are parsed before a metric or check is authored. Invalid syntax returns a validation error; a rejected replacement keeps the original check and its activity history intact.

Protected research runs require analytics access before a person can resume or warm a successor. The successor’s bound sandbox can read the verified source history through authenticated log routes, but cannot modify the source run.

## Follow-up measurement timing

Metric follow-up checks wait until their full trailing query window contains only post-resolution data. The configured soak is an independent minimum wait. Reopening a report clears the measurement anchor; resolving it again starts a new window. Legacy active metric checks without an anchor start their window at the next coordinator tick and recalculate expiry from the remaining schedule, capped at 90 days from that tick. Legacy rows do not distinguish supplied expiries from defaults, so both follow this re-arming policy. Checks with an existing anchor retain their expiry. A window that cannot finish before expiry records an inconclusive result instead of scheduling an unreachable run. Agent checks keep their soak-based schedule.

New metric checks validate numeric goals and baselines against their metric kind, format, unit, and query. Existing check configurations remain readable.

## Repository selection

The shared repository selection prompt asks the agent to check the sources in the supplied context before choosing a repository.
For information from a private repository or another explicitly private source, it prefers a relevant private candidate and returns no repository if none is suitable or its visibility cannot be confirmed.
Each candidate carries a private, public, or unknown label from the cached GitHub repository list, so the agent does not query GitHub for visibility.
This is prompt guidance, not an enforced access control, and it does not validate repositories selected outside the agent.

## Reviewer notifications

Research suggests reviewers from relevant commit authors and recent code activity. It also checks the finding's relevant paths against `owners.yaml` and the connected repository's CODEOWNERS. When they disagree, the `owners.yaml` owner comes first and a routable CODEOWNERS owner follows. A human edit to the report's reviewer list stays in place on later research runs. Missing ownership files or paths leave the existing author-based suggestions unchanged. Scout-authored reports use their own reviewer selection guidance.

When a project member adds a reviewer, the report shows "Added by" and that member's name as the reason above the reviewer. The name comes from the authenticated author of the artefact that added the reviewer, not from the editable reason. If the author is unavailable, the report shows the generic "Added by teammate" badge instead.

Slack notifications for a ready report include only reviewers who have access to the report's project when delivery starts.
The same access rule applies when a reviewer is added later.
If no suggested reviewer has access, the ready report still goes to the configured team channel without reviewer mentions.

## Report links

Only scouts and the signals pipeline create and manage typed, directed report links.
Scouts attach them through the `links` list on `scout-edit-report`.
Public callers can read `report_link` artefacts, but cannot create, edit, or delete them through the artefact API.
Typed links cannot yet be removed through a supported operation.
[Issue #102776](https://github.com/PostHog/posthog/issues/102776) tracks the unlink API and MCP tool.
The Implement button overrides an automatic start check; it does not remove a link or change plan membership.
Links must name a different live report in the same project and cannot form a cycle among links of the same kind.

Research reads a report's outgoing `follow_up_of`, `depends_on`, and `part_of` links and starts from the linked reports' findings and pull requests.
A linked report must have an explicit safe verdict in its latest safety judgment.
Research uses the latest finding for each signal and removes repeated links.
It loads at most ten distinct relationships it can use and limits the rendered context to 12,000 characters.
All linked fields are escaped and marked as untrusted evidence.
A follow-up can refer to a manual fix or a regression; it must not invent a missing pull request.

Three link gates hold back automatic implementation, and each one records why on the report:

- A report that duplicates another one does not start its own work when any report on that duplicate chain is resolved or already carries a pull request.
- A report that depends on another one does not start until that dependency carries a pull request.
- A report that other reports are `part_of` never starts its own work, because its steps do the work.

Link readers use the writer database so a new link takes effect without replica delay.
The implementation path checks the gates again under the report lock before it creates a task.
The gates apply to automatic implementation only.
Pressing Implement in the inbox starts a run whatever the links say.
Nothing re-evaluates a held-back report when its dependency's pull request opens, so it starts on the report's next pipeline evaluation or by hand.

## Recurrence after a fixed verdict

A report dismissed as `already_fixed`, `fixed_outside_posthog`, or `pr_merged` can create a new report when the issue returns.
The pipeline records the new report's parent with a typed `recurrence_of` report link.
A report created because a follow-up check failed on a resolved report also gets a typed `follow_up_of` link to that report, carrying the verdict as the link's reason.
Generic `related_to` links do not control signal assignment.
Later signals follow the recurrence chain, even if an older parent is restored.
Matching selects the current successor before the specificity check, so the check uses its signals and title.
Traversal passes through deleted intermediate reports without assigning signals to them.
A successor dismissed for a preference reason keeps absorbing signals, including signals that match an older parent.
Repeated fixed feedback does not create another successor.
A new dismissal without feedback clears the fixed claim from an earlier dismissal cycle.
Automatic suppression after an unmerged PR closes also records an empty dismissal.
The state API rejects fixed reasons with `potential`; use `suppressed` or `resolved` for a fixed claim.

This change does not recover historical signals automatically.
Older dismissal records cannot reliably identify the active dismissal cycle.
Historical recovery needs a verified transition history before it can create new reports.
Research context excludes parent reports whose latest safety judgment rejects their content.
New reports do not copy the title or summary from these unsafe parents.
Legacy `related_to` links supply context only for resolved parents. Fixed-dismissed parents require a typed recurrence link.

The state API also accepts resolution from `failed`.
The web inbox offers Resolve for failed reports.
The Needs decision section includes failed reports, even without an actionability judgment.
Its `needs_decision` API view also includes actionable ready or pending-input reports without an implementation PR.
Triage warns before a verdict closes an open implementation PR.
New failed reports consume a daily inbox slot when they first become visible.
Existing failed reports without a visibility timestamp remain historical backlog; they do not consume the rollout day's slots.
The desktop eligibility change must ship separately after this backend transition is deployed.
A suppressed report can resolve if its prior status was `ready`, `pending_input`, `failed`, or `resolved`.

## Scout revisions

Scout edits increment the content revision count only when the title or summary changes. Notes, evidence, routing updates, and unchanged text do not spend a revision. The edit response always includes the report's running revision total.

The revision and corroboration counters are nullable, with no database or model default. Reads treat `NULL` as zero, so existing reports and reports created by older workers need no backfill. The migration adds nullable columns without rewriting rows or validating a `NOT NULL` constraint. PostgreSQL still needs a brief exclusive table lock to add the columns.

A scout can request a replacement when its rewrite changes the fix. The server binds that decision to verified automated predecessor PRs and the exact research pass and content revision. It starts at most one replacement per version, within the scout revision cap, and stops automatic closure if another edit changes the report while the replacement runs. Free-form scout notes always remain individual activity entries. Only notes explicitly marked `corroboration_only` count towards the four-confirmation cap; later confirmations increase the collapsed count shown by both the web and desktop inboxes.

Autostart binds task content to the report title, summary, research pass, and scout revision captured before external lookups. It checks that snapshot under the report lock before stamping a version as implemented, and retries from current content if the report changed.

Supersession verifies predecessors only for a real rewrite within the revision cap. Missing or stale verification rejects the edit before commit so the same request can be retried. GitHub calls happen outside the report lock.

An accepted scout replacement decision commits a protected `implementation_dispatch` artefact with the edit. A Celery worker resumes repository preparation, retains the editing scout's owner exclusion, and rechecks the exact decision before creating a task. Technical failures retry with exponential backoff from one minute to fifteen minutes. A five-minute sweep recovers lost queue messages and expired worker leases in bounded pages. The dispatch state records pending, processing, retrying, blocked, started, or canceled work; it is available through the existing artefact API. A policy block waits for a new edit or research trigger, rather than starting automatically when a setting or quota changes.

Only the first four content revisions can request a scout replacement, including revisions that did not request one. An over-cap request preserves the rewrite and records the revision-limit reason without claiming that the old fix is still correct. Reports under active research cannot accept a supersede claim. The current revision count is read inside the edit transaction, so a failed read cannot report a failed edit after committing a note or evidence.

## Verification plans

After research completes, actionable reports can include a `Verification plan` note for the implementation agent.
This final request is optional: if generation or note conversion fails, research still completes without the note.
The findings, actionability, priority, title, and summary remain available.
Core research failures and cancellation still fail the run and trigger session cleanup.

Verification proposals can name `existing_check_id` to revise an open check while preserving its remaining recurrence. An unchanged rounded `soak_hours` preserves the original minute precision; an explicitly changed wait replaces it. Equivalent default-valued config fields do not reset approval. Invalid stored configs do not prevent a valid proposal from replacing them. Presentation receives current checks as untrusted evidence, and verification can align the final Expected impact prose with its proposed metric goals.

Research traces that contain existing metric-check context require the same analytics permissions as the check query and baseline, including for resumed runs, Max task tools, trace analysis, task summaries, and run details. A sandbox token’s exception covers only the run on which the server records its token ID; task-wide reads and other runs still require analytics access. Checks without a stored query contribute neither a query marker nor an unproven baseline to the research trace. Authorized readers retain summaries and run details; direct storage links remain withheld. Query provenance is private server-owned run state inherited on resume, so ordinary task reads do not scan ancestors. Legacy checks inherit missing display formats only from a report metric with the same stored query. When a suggestion task finishes, the selected report refreshes its prose as well as its checks.

Metric suggestions are available only when `signals-report-checks-replace` enables the replacement tool.

The note names proposed follow-up checks without claiming they were scheduled. The Follow-up checks sidebar shows the stored checks. If any optional check spec is malformed, research keeps valid verification prose and skips check reconciliation, preserving existing checks. An explicitly empty, valid check list still retires omitted checks. Legacy activity payloads preserve approved, person-authored, and nonpending checks. Referenced checks inherit their existing wait when the proposal omits it. Verification’s revised summary is saved only after its check reconciliation succeeds, so a skipped or invalid proposal cannot change Expected impact prose independently of the stored checks.

The plan separates `Confirm the current state` guidance from `Confirm the outcome` guidance.
Each section says what evidence to collect, which result supports a conclusion, and which result is inconclusive.
The guidance can use a query, test, log search, replay, code review, or manual check, and does not prescribe a resolution.
Report retrieval directs any agent to the work log, where verification guidance applies regardless of how the agent started.
The agent checks that the note matches the current findings and confirms the current state before it starts work.
It confirms the outcome after the chosen resolution.
If current evidence shows the issue is gone, it records that result and stops; if no note applies, it verifies the issue from the report's evidence.
Missing data, failed checks, and inconclusive results do not establish that the issue is fixed.

## Opening a report task

When a report has a linked task run, the View task button opens it in the PostHog AI sidebar.
The button fits its label, including when it appears below the Solution section.
