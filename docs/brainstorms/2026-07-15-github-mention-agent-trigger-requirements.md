---
date: 2026-07-15
topic: github-mention-agent-trigger
---

# GitHub @-mention → agent task trigger

## Problem Frame

Signals (the self-driving product) opens autonomous PRs.
When a human reviews one and wants changes, the feedback loop is broken:
they leave a comment, and nothing happens.
To get the agent to act, they have to leave GitHub and go back to PostHog.
People want to stay in GitHub — drop notes on the PR, @-mention the PostHog bot,
and have the agent address the feedback and push commits to the same PR.

We already have a GitHub App (installed via project integrations) and a webhook that receives
`issue_comment` events.
Every existing trigger surface (Slack bot, Signals autostart) funnels into one shared launch
interface (`tasks_facade.create_and_run_task`).
A GitHub mention is a new front door to that same engine.

The headline routing worry — "one repo can belong to many projects; a project can have many
repos" — does **not** apply to this first version.
A Signals PR is already authoritatively linked to exactly one project via its originating task,
so we inherit the project from the PR rather than infer it from the repo.

## Requirements

- R1. When an eligible commenter @-mentions the PostHog bot in a conversation comment on a PR that
  Signals opened, a follow-up agent task is launched for that PR's project.
- R2. Routing is inherited, not inferred: the project, repo, and originating report context come
  from the Task that opened the PR (resolved from the PR URL via the existing PR-URL → TaskRun
  binding). No repo→project disambiguation is performed. The PR URL for a comment comes from
  `payload.issue.pull_request.html_url`.
- R3. **Runs as the commenter, with real attribution.** The follow-up task runs as the commenter's
  PostHog user and pushes commits authored by them. This requires the commenter to have a _usable
  personal GitHub connection_ (a personal GitHub integration with repo-write scope — the token
  that actually lets us push as them), to resolve to an **active member of the PR's project's
  org**, and to be identified by the **immutable GitHub account id** from the webhook payload —
  never the login string (which can be renamed/reused). Launch uses `origin_product=GITHUB` and
  `interaction_origin="github"`.
- R4. **Connect-gate for un-connected commenters.** If the commenter does not have a usable
  personal GitHub connection (none connected, or it lacks the required scopes) — including a GitHub
  account we cannot yet resolve to any PostHog identity at all — no run starts yet. Instead the bot
  immediately posts a comment on the thread with a **direct link to connect (or re-scope) their
  personal GitHub connection**, and records a **pending-mention row** in a new Postgres table (keyed
  by the commenter's GitHub account id, plus PR URL, comment id, repo, and timestamp). The row is
  claimed by whoever later connects that exact GitHub account, so an unknown account is never a
  dead-end.
- R5. **Replay on connect.** When a user connects a personal GitHub connection for the first time,
  or upgrades an existing one to include the required scopes, a background job replays that user's
  pending mentions from the **last 12 hours** — matched by immutable GitHub account id, launching a
  follow-up task for each and marking the row processed. Rows older than 12 hours are ignored;
  processed rows never re-run. Org membership and routing are re-resolved at replay time (from the
  PR → task → team), so a replayed mention on a PR outside the connecting user's orgs is dropped.
- R6. **Feedback scope.** The agent addresses the PR description body (including the reviewer's
  markdown notes) + the triggering comment + conversation comments authored by org members.
  Comments from non-members (possible on public repos) are untrusted context, not actionable
  instructions. Inline code-line review comments are out of scope for v1.
- R7. **Untrusted input.** Comment and description text is treated as data, not trusted
  instructions. Mention-triggered runs execute with constrained tool/egress scope to mitigate
  prompt injection, since the agent acts on attacker-influenceable text while holding a
  push-capable token.
- R8. **Push to the existing branch.** The agent addresses feedback by pushing commits to the
  existing PR head branch — it does not open a new or stacked PR.
- R9. **The loop always visibly closes.** The bot posts (a) a prompt acknowledgement — a reaction;
  (b) a short "done in `<commit>`" reply beneath each conversation comment it acted on; and (c) one
  terminal summary comment covering the overall outcome: what it addressed (with commit refs), what
  it deliberately skipped or couldn't do (with reasons), needs-clarification, run-failed, or
  connect-required (the R4 reply). No run ends silently.
- R10. **Summary safety.** The completion summary describes code changes only and must not include
  project or customer data or internal reasoning — PR comments may be world-readable.
- R11. **Trigger-volume guards.** Per-PR / per-user debounce; a new mention while a run is in flight
  **queues behind it** (becomes a follow-up run once the current one finishes) rather than spawning
  a parallel run; an org-level kill switch exists. The identity gate bounds _who_, not
  cost/frequency, so it is not a cost control.
- R12. **On by default** for Signals PRs, with no per-project setup. The R11 kill switch is the
  off-switch.
- R13. **Inbox stays in sync.** The mention-triggered follow-up run is recorded against the linked
  Signals report's existing artefact/task log (reusing the `record_implementation_task` /
  `SignalReportTask` path), so the report in the inbox reflects the human-feedback iteration. No
  report status change — the existing PR-merge → RESOLVED webhook still owns report status.
- R14. **The agent never changes the PR's draft/ready state.** Addressing feedback does not flip a
  draft PR to ready-for-review (or vice versa); readiness is a human decision.

## Success Criteria

- An org member who has connected GitHub can comment "@posthog address the notes in the
  description" on a Signals PR and, without leaving GitHub, get commits **authored by them** pushed
  to that PR's branch addressing the description + member feedback, plus a summary comment.
- A member who has _not_ connected GitHub gets an immediate reply with a one-click connect link;
  after they connect, their original mention (if within 12 h) is processed automatically — the
  single comment still results in commits. No dead-end.
- An unlinked/unresolvable or non-member commenter never causes a run; at worst a run is attributed
  to the wrong person or triggered by an outsider — neither is possible because the account-id gate
  and org-membership check are the sole trust boundary (repo access is not, on public repos).
- Zero repo→project disambiguation logic ships.

## Scope Boundaries

- No @-mention handling on human-created PRs or bare issues (only Signals-opened PRs). The general
  "mention the bot anywhere" case — where repo→project routing actually has to be solved — is
  deferred to a phase 2.
- No inline code-review comment handling (would require `pull_request_review_comment` /
  `pull_request_review` events; v1 uses only `issue_comment`).
- Agent pushes to the existing PR head branch; no new or stacked PRs.
- Non-member comment text is treated as context, never as actionable instructions.
- No general "process all of a user's past GitHub comments" backfill — replay is bounded to the
  recorded pending-mention rows from the last 12 hours.
- No thread "resolution" in v1 — conversation-level comments can't be resolved via the API (only
  inline review-comment threads can, and those are out of scope). Closure is signalled by the
  per-comment replies + terminal summary (R9).
- The agent does not change the PR's draft/ready state (R14).

## Key Decisions

- **Signals-PRs-only first** (vs general mention-anywhere): sidesteps repo→project ambiguity and
  closes the highest-value loop.
- **Description + member conversation comments** (vs whole review state incl. inline comments):
  keeps v1 on the already-received `issue_comment` event and shrinks the injection surface.
- **Require a real personal GitHub connection, run as the commenter, with a graceful connect-gate**
  (vs the strict "reject unlinked" original, and vs trusting repo access + running as the PR owner).
  Rationale: the review showed the naive strict path both breaks first-use _and_ fails to deliver
  attribution (most commenters lack a push token, so their commits would land as the bot anyway).
  Requiring the personal connection gives real git attribution; the connect-gate + 12 h replay
  removes the first-use dead-end so the member's single comment still resolves. Rejected
  alternatives: run-as-PR-owner (loses attribution, fails open on public repos); fetch-all-past-
  comments via GitHub's search API (`commenter:` qualifier is rate-limited and eventually
  consistent — the pending-mention table is the reliable mechanism).
- **Immutable GitHub account id as the identity key** on both the webhook side and the connect
  side: the connect OAuth proves control of the account, making the replay binding verified rather
  than a spoofable login-string match.
- **On by default with a kill switch** (vs opt-in toggle): the identity gate bounds who can trigger;
  the kill switch + volume guards bound cost.
- **Unknown commenters get the same graceful path** (vs staying silent): a mention from a GitHub
  account with no PostHog identity yet still gets a connect link + a pending-mention row keyed by
  account id, so a genuine first-time teammate is never lost.
- **Re-mentions queue** (vs supersede or ignore): a mention during an in-flight run becomes an
  ordered follow-up run — nothing is dropped and no parallel run spawns.
- **Granular per-comment acknowledgement** (vs a single summary): a "done in `<commit>`" reply under
  each addressed comment plus a terminal summary. Chosen for closure clarity over minimal write-back
  count.
- **Record the iteration on the linked report, no status change** (vs untouched, or a louder inbox
  notification): keeps the inbox coherent without adding notification noise; PR-merge still owns
  report status.

## Dependencies / Assumptions

- **Identity mapping mostly already exists** — this was the doc's earlier "main unknown" and it is
  largely resolved. `products/signals/backend/report_generation/resolve_reviewers.py::resolve_org_github_login_to_users`
  maps a GitHub login → org-member `User` scoped by org membership, and `posthog/models/user_integration.py::UserIntegration`
  (kind=github) stores login/account-id + user-to-server tokens. Reuse these rather than build a new
  linking flow. The genuine residual is whether a matched user has a _push-capable_ token (that's
  exactly what the connect-gate secures).
- **The shared webhook dispatcher must be modified, not passively reused.** `posthog/urls.py::github_webhook`
  does `return dispatch_github_event(...)` and terminates; `issue_comment` is currently consumed by
  the Conversations product and gated on that product's per-team `github_enabled`, so a Signals-only
  team drops the event today. Mention detection must be wired into the dispatcher (before/alongside
  conversations routing), and the primary→secondary region proxy must route the run to the region
  that owns the PR's team.
- **A new "push to existing PR head branch" run mode is needed.** `tasks_facade.create_and_run_task`
  exposes `create_pr` + `branch` but the current workflow opens a _new_ draft PR (the Signals path
  forces `pr_authorship_mode=BOT`, `run_source=signal_report`). "Check out this remote head and push
  commits to it" is new capability, not a config flag.
- Reuse the PR-URL → TaskRun binding (`products/tasks/backend/webhooks.py::find_task_run`) to resolve
  the originating task; it depends on `TaskRun.output.pr_url` having been recorded.
- Assumes the GitHub App is subscribed to `issue_comment` events in production (it is, for
  Conversations), and that the installation token can post the ack/terminal comments.

## Outstanding Questions

### Resolve Before Planning

- (none — all blocking product decisions resolved)

### Deferred to Planning

- **Affects R4/R5 (Technical):** Exact wiring into `github_webhook` / `dispatch_github_event` so
  mention detection and Conversations routing coexist, plus region-proxy handling.
- **Affects R5 (Technical):** The replay trigger point — the hook fired on personal-GitHub-integration
  create / scope-upgrade — and its idempotency against the pending-mention table.
- **Affects R4 (Technical):** The connect deep-link: which existing integration-connect URL, the exact
  required scopes, and how to carry return context so connect → replay is seamless.
- **Affects R8 (Technical):** Whether `create_and_run_task(create_pr=False, branch=<PR head ref>)` can
  clone + push to the existing head, or a new push-only run mode must be built.
- **Affects R1 (Technical):** `X-GitHub-Delivery` dedup + loop prevention (the bot's own ack/terminal
  comments must not re-trigger).
- **Affects R11 (Needs research):** Whether GitHub's search API (`commenter:` qualifier) is viable as a
  backfill fallback (expected: no — the table is authoritative).

## Next Steps

→ `/ce:plan` for structured implementation planning.
