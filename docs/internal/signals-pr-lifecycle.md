# Report completion and late PR attachments

A report completes after all linked implementation PRs are closed or merged.
At least one merged PR resolves the report; otherwise all closed PRs suppress it.

Attaching a new open, draft, or unknown PR to a resolved report returns it to ready.
The shared PR-linking service applies this rule to task outputs and agent attachments.
An existing attachment retry does not reopen a report, and importing legacy assignments preserves its status.
Suppressed reports remain suppressed when another PR is attached.

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

## Automatic PR replacements

Research can replace a selected subset of obsolete PRs from verified automatic implementation runs. A completed automatic owner can transfer its claim even when its own PR is retained, so a later pass can replace another retained predecessor. Human claims, active runs, and manual continuations prevent automatic claim transfer.

Users can retry or continue the latest replacement task, including after failure or incomplete handover. Historical automatic implementations in its replacement history do not consume another run slot. Unrelated work and later manual runs still block the slot. Continuing a task with pending handover changes the handover to `needs_attention` before dispatching the user run. Earlier PRs stay open for manual review, and terminal handovers are not restarted.

Immediate callbacks schedule handover after run or report changes. A five-minute recovery sweep also checks persisted replacement records in pages of 500, without an age cutoff. It skips terminal handovers and active worker leases, and retries missing or expired processing records through the same bounded reconciliation task. A partial index limits the scan to replacement records. Recovery logs report scanned records, successful dispatches, and dispatch failures; malformed records are logged and skipped.

PR activity matches metadata by case-insensitive repository identity and PR number. Links retain their original URL, while closure outcomes remain separate from the latest known GitHub state.
