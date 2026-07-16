# RFC: Review correctness at 10,000 PRs a month

Status: draft, looking for feedback from the teams that own the pieces (stamphog, ReviewHog, engineering analytics, Signals).

## Problem

PR volume is heading toward 10,000 a month.
Most code is now written with agents, and most review is agent-assisted.
That combination creates three problems that none of our existing tools addresses end to end:

1. **Correlated blind spots.**
   When an agent writes the code, the author's agent pre-reviews it, and the reviewer's agent reviews it again, all three passes can share the same model biases.
   A class of bug that the model family systematically misses will sail through every layer.
2. **Fragmented review tooling with no shared learning loop.**
   Engineers have each built personal review skills, hooks, and adversarial passes.
   The experimentation is healthy, but the learnings stay private: a gotcha one engineer's skill catches never reaches anyone else's, and nothing measures which approach actually works better.
3. **Knowledge atrophy.**
   It is now normal to ship a correct change to a system you don't understand.
   ELI5 prompts and diagrams patch the tactical gap, but nothing tells us when a subsystem has lost all humans with deep familiarity — until an incident finds out for us.

The common thread: review quality is currently unmeasured.
We measure the product obsessively and the review system not at all.

## What we already have

The repo is better positioned than the problem statement suggests.
The building blocks exist; they just don't feed each other yet.

| Asset                      | Where                                    | What it gives us                                                                                                                                                                                                                             |
| -------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ReviewHog                  | `products/review_hog/`                   | Production AI PR reviewer (perspectives → blind-spot pass → validation → inline comments). Findings persist in Postgres (`ReviewReportArtefact`) with file/line. Manual eval program in `eval/` with a frozen-PR yardstick and an LLM judge. |
| Stamphog                   | `tools/pr-approval-agent/`, `.stamphog/` | AI approval bot with deterministic risk tiers and deny-lists, plus a per-author familiarity signal (git-blame overlap, prior PRs, recency). Emits `stamphog_review_completed` events.                                                        |
| Engineering analytics      | `products/engineering_analytics/`        | HogQL read layer over `github_pull_requests` / `github_workflow_runs` warehouse tables, CI cost and LLM-spend joins, MCP tools. Stated north star: emit CI Signals.                                                                          |
| Signals scouts             | `products/signals/`                      | Autonomous sandboxed agents that watch any warehouse-reachable data source on a schedule and file findings to the inbox. None watch engineering data today.                                                                                  |
| Eval harness               | `products/posthog_ai/eval_harness/`      | Braintrust-backed sandboxed evals with pluggable `setup()` hooks and LLM-judge scorers.                                                                                                                                                      |
| Commit provenance trailers | every agent commit                       | `Generated-By:` / `Task-Id:` trailers, stamped by agent tooling. In a 30-PR sample of recently merged PRs, 22 carried them on their head commits.                                                                                            |

And the specific gaps, verified by exploration:

- Nothing reads the provenance trailers. Agent authorship is stamped on most merged code and consumed by nothing.
- No benchmark of historical PRs with ground-truth findings exists, so review-skill quality is anecdote.
- No loop feeds escaped bugs (reverts, fix-follow-ups) back into review guidance; the incident-pattern corpora are hand-edited.
- The fate of ReviewHog findings (addressed, dismissed, ignored) is not tracked.
- Stamphog's familiarity signal is computed per run and thrown away; there is no per-subsystem trend.
- No scout watches PR/CI data, and nothing applies our own Experiments product to the review process itself.

## Proposal

Six initiatives, sequenced so that each produces the data the next consumes:
telemetry → provenance → benchmark → flywheel → atrophy signal → experimentation.

### 1. Provenance pipeline

**Goal:** make "was this agent-written, by which tool, from which task" a queryable dimension, so escape rates and review routing can condition on authorship.
This is the foundation for attacking correlated blind spots — for example, routing agent-authored code in sensitive areas to a review pass on a different model family, once the data shows where that matters.

**v0 (shipping now):** stamphog parses the trailers from the PR's head commits at review time and captures `stamphog_agent_authored` / `stamphog_generated_by` / `stamphog_task_ids` on its existing event.
Head commits, never the squash-merge commit — squash merges can drop or rewrite trailers.

**v1:** a batch layer in `products/engineering_analytics/`: a `PullRequestProvenance` model populated by a scheduled task (recent merged PRs from the warehouse table → GitHub commits API → trailer parse), exposed as a HogQL view joinable to `github_pull_requests` and the existing LLM-spend join, plus a 90-day backfill command.

**Not yet:** review routing by provenance. Wait until provenance × escape data proves the correlation.

### 2. Review-outcome telemetry

**Goal:** know the fate of every ReviewHog finding — addressed, reacted to, or ignored.
This is production precision for the reviewer, the primary ground-truth feed for the benchmark (initiative 3), and the outcome metric for experimentation (initiative 6).

**v0:** a post-review task in `products/review_hog/backend/` that, for each PR with a `ReviewReport`, classifies each finding by whether a later commit touched the finding's file near its line, or its comment thread got a reply/resolution, and emits one `reviewhog_finding_outcome` event per finding.
Line-proximity heuristic first; measure its noise before spending tokens on LLM judging of whether a fix truly addressed a finding.

### 3. ReviewBench

**Goal:** one benchmark any review approach can run against — ReviewHog perspective sets, the qa-team skill, engineers' personal skills.
A leaderboard dissolves the fragmentation empirically instead of by decree: personal skills become scored submissions, and the winners get promoted into the shared perspectives in `products/review_hog/skills/`.

**v0:** frozen cases in a new `products/review_hog/evals/` suite (the eval-harness auto-discovery path, distinct from the existing manual `eval/`).
A case is a frozen diff plus base SHA plus a curated ground-truth finding list; case zero is the frozen PR and finding yardstick the ReviewHog team already uses.
The harness's sandbox `setup()` checks out the base SHA and applies the diff; an LLM-judge scorer ports the existing judge prompt and reports precision/recall per case into Braintrust, whose experiment comparison is the leaderboard.

**Ground truth mining:** human review comments followed by pre-merge commits touching the same lines, validated by an LLM judge and human-curated before freezing.
Target 20–30 high-precision cases; precision of ground truth beats volume.

**Guardrails:** the judge must run on a different model family than the reviewer under test, or the benchmark inherits the blind spots it exists to measure.
Runs are nightly or label-triggered, never per-PR — a full reviewer run per case is expensive.

### 4. Knowledge-atrophy signal and learning briefs

**Goal:** a subsystem-level signal that no strongly-familiar human has meaningfully touched a subsystem recently, plus a weekly per-team digest of what changed in their systems.

**v0 (shipping now):** stamphog computes familiarity on every LLM-reviewed run (previously only one tier) and captures the band, blame overlap, prior-PR count, recency, and owning teams on its event.
The reviewer prompt is unchanged outside the tier that already used the signal — this is telemetry, not a behavior change.

**v1:** a scout (`signals-scout-engineering-health`) that aggregates those events **by owning team/subsystem — never by author** and files an inbox finding when a subsystem's trailing-30-day merged PRs contain no strongly-familiar human authorship.
The same scout drafts the weekly "what changed in your systems" brief.

**Not yet:** auto-generated architecture atlases and diagram pipelines. Briefs deliver most of the value at a fraction of the cost.

### 5. Escape-mining flywheel

**Goal:** an automated loop from escaped bugs back into review guidance.
Every revert or fix-follow-up becomes an escape report: what shipped, what review said at the time (joinable to `ReviewReportArtefact` and the finding-fate events), and what check would have caught it.

**v0:** a scout (`signals-scout-engineering-escapes`) watching the `github_pull_requests` warehouse table for merged PRs that revert a recent PR, and `fix:` PRs referencing a PR merged within the previous two weeks.
Weekly cadence, strict thresholds, findings to the inbox.

**v1 (gated on v0's mining precision):** the scout drafts PRs — agent-authored, human-approved — adding mined patterns to the incident-pattern corpus, the blind-spot skills, and ReviewBench cases.
This closes the loop that today does not exist: review guidance that updates itself from what review missed.

### 6. Experimentation on the review process

**Goal:** reviewer topology and skill changes ship as experiments, not vibes.
Variant assignment via a feature flag on the reviewer config, a `review_variant` property stamped on reports and finding-outcome events, outcomes measured as finding-acceptance rate and downstream escape rate, with a ReviewBench score as the offline gate before any live variant.

**v0:** one real experiment picked from the ReviewHog team's existing candidate list, using their manual topology exploration as the prior.
Explicitly no platform-building — one flag, one stamped property, one analysis.

## Non-goals

- **No per-person rankings, anywhere.**
  Engineering analytics already locks this out and every new surface here inherits it: aggregation, dashboards, scout output, and the ReviewBench leaderboard rank subsystems and skills, never people.
  Familiarity events carry an author like every other analytics event, but no new surface may render a per-person comparison.
- **No mandatory consolidation of personal review skills.**
  The benchmark makes the shared reviewer the best option by measurement, not by policy.
- **No per-PR benchmark gating.** CI cost and latency stay flat.

## Risks

- **Squash merges and trailer loss.** Mitigated by parsing head commits only; the trailer-prevalence sample above says the dimension is well-populated today, and the batch layer should keep monitoring it.
- **Noisy ground-truth mining.** Comment-then-change includes coincidences. Mitigated by LLM-judge validation plus human curation, and by keeping the benchmark small and high-precision.
- **Correlated judges.** The benchmark judge must not share a model family with the reviewer under test; the hand-curated yardstick stays as the calibration anchor.
- **Ownership boundaries.** These pieces live in three products owned by different teams. Each initiative should be co-designed with the owning team; in particular the benchmark must extend the ReviewHog team's existing eval culture, not replace it.

## First steps

1. Stamphog telemetry enrichment (initiative 1 v0 + initiative 4 v0) — small, single-tool, starts the baseline accruing immediately.
2. This RFC, for feedback and sequencing.
3. Next: the finding-fate task (initiative 2), then the provenance batch layer, then ReviewBench case zero with the ReviewHog team.
