# CI capacity: GitHub Actions limits vs 10,000 PRs/month

How close the monorepo is to each [documented GitHub Actions limit](https://docs.github.com/en/actions/reference/limits#existing-system-limits), measured against real execution data, and what to do about each as we scale toward the DevEx goal of shipping 10,000 PRs a month.

All numbers were measured on 2026-07-07 with the commands and queries in [Methodology](#methodology), so they can be re-run to refresh this doc.

## TL;DR

Three limits matter right now; everything else has comfortable headroom at 1.6x growth.

1. **Workflow run queue cap (500 runs/10s per repo): already breached.** 1,258 `startup_failure` runs in June, 2,164 in the first week of July alone. A single stacked-PR restack created 1,328 runs in 20 seconds. Each push fans out to ~35-46 workflow runs, so ~11 simultaneous pushes exhaust the entire repo's budget and take unrelated runs down with them.
2. **Concurrent GitHub-hosted standard jobs (500 on Enterprise): at the edge.** Measured peak of 462 concurrent jobs from just the 4 workflows that emit job telemetry; the true peak across all 97 workflows is higher. Excess jobs queue rather than fail, so this shows up as CI latency, not red X's.
3. **Actions cache (10 GB per repo): full.** 10.16 GB across 168 caches means LRU eviction churn is already happening, silently degrading cache hit rates.

At 10,000 PRs/month (1.6x current volume) without changes: burst failures become a daily occurrence for anyone pushing stacks, hosted-runner queue latency becomes routine at peak hours, and cache eviction worsens. None of these are cliffs at exactly 10k; all three are already binding today and scale linearly with volume.

## Current scale (June-July 2026)

| Metric                                          | Value                                   | Source                               |
| ----------------------------------------------- | --------------------------------------- | ------------------------------------ |
| PRs created, June 2026                          | 6,214                                   | GitHub search API                    |
| PRs merged, June 2026                           | 4,648                                   | GitHub search API                    |
| Workflow runs, June 2026                        | 1,489,731 (~50k/day avg)                | Actions runs API                     |
| Workflow runs, Mon Jul 6                        | 86,337                                  | Actions runs API                     |
| Workflow files                                  | 97 (157 registered incl. removed)       | repo / workflows API                 |
| Runs per PR push                                | ~35-46                                  | workflow trigger analysis            |
| Jobs per full PR push                           | ~190-215 (incl. 52-shard Django matrix) | workflow matrix analysis             |
| Jobs per weekday (4 telemetered workflows only) | ~87k-126k                               | `posthog-ci-running-time-job` events |
| Org plan                                        | Enterprise (GHEC)                       | orgs API                             |

Runs on Jul 6 by trigger: `pull_request` 66,987 (78%), `workflow_run` 5,872, `push` 5,694, `issue_comment` 2,066, `pull_request_review` 1,636, `pull_request_review_comment` 856, `schedule` 61, `merge_group` 0.

The 10,000 PRs/month goal is only ~1.6x current created volume, so "limits at 10k" mostly means "limits we are brushing today, 60% worse".

## Limit-by-limit status

Values from the [GitHub Actions limits reference](https://docs.github.com/en/actions/reference/limits#existing-system-limits). "Headroom at 1.6x" assumes run volume scales linearly with PR volume.

| Limit                                  | Documented value                                  | Measured status                                                                                                                                                                                           | Headroom at 1.6x                                                     |
| -------------------------------------- | ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Workflow runs queued per repo          | 500 / 10 seconds (excess **blocked**, not queued) | **Breached.** 1,258 startup_failures in June; 2,164 Jul 1-7. Measured burst: 1,328 runs created in 20s (Jul 6 18:01 UTC), 916 of them from one user restacking ~21 branches. Baseline is ~53 runs/minute. | None. Gets worse linearly; bursts are the problem, not averages.     |
| Concurrent GitHub-hosted standard jobs | 500 total (Enterprise; support can raise)         | **At the edge.** Peak 462 concurrent jobs/minute measured from only Backend CI, Frontend CI, Storybook, and E2E Playwright telemetry. All other workflows' `ubuntu-*` jobs add on top.                    | Negative. Peaks would exceed 500 regularly; excess queues (latency). |
| Actions cache per repo                 | 10 GB (not raisable)                              | **Full.** 10.16 GB across 168 active caches; LRU eviction active.                                                                                                                                         | Negative without cleanup.                                            |
| GITHUB_TOKEN API rate                  | 1,000/hr baseline; higher for GHEC                | OK. Observed live limit is 30,000/hr (core bucket); one sampled window showed ~8.6k used (~29%). The `search` bucket (30/min) is the tight one.                                                           | OK, but see the telemetry gap below.                                 |
| Workflow trigger events                | 1,500 events / 10s (support can raise)            | OK. Even a 21-branch restack is only ~21-40 events; the 500-runs cap binds ~30x earlier because each event fans out into ~35-46 runs.                                                                     | OK.                                                                  |
| Job matrix                             | 256 jobs per workflow run                         | OK. Largest is the Django matrix at 52; theoretical cap 150 (`DJANGO_MAX_SHARDS=50` across 3 segments).                                                                                                   | OK.                                                                  |
| Reusable workflow nesting / uniques    | 4 levels / 20 unique per run                      | OK. Max 2 levels, 3 reusable workflows total.                                                                                                                                                             | OK.                                                                  |
| Re-runs per workflow run               | 50                                                | OK.                                                                                                                                                                                                       | OK.                                                                  |
| Check runs per check suite             | 50,000                                            | OK (~200-1,000 per SHA).                                                                                                                                                                                  | OK.                                                                  |
| Job execution time (hosted)            | 6 hours                                           | OK. Every job declares `timeout-minutes` (CI-enforced).                                                                                                                                                   | OK.                                                                  |
| GitHub-hosted minutes                  | 50k/month included (Enterprise), then billed      | Cost lever, not availability: ~83k-135k hosted minutes per weekday (~2.6-2.9M/month pace) from the 4 telemetered workflows alone. Depot side: ~450k-730k min/day.                                         | Linear cost growth.                                                  |
| Artifact storage                       | 50 GB included (Enterprise), then billed          | Growing: Playwright reports/screenshots at 30-day retention; two 90-day retentions in `ci-backend.yml` (`migrated-schema`, `test-selection-verdict`).                                                     | Linear cost growth.                                                  |

### Mechanics worth understanding

- **The 500/10s cap counts runs, not jobs, and a run that calls reusable workflows counts once.** Consolidating always-fire PR workflows directly divides burst consumption; shrinking matrices does nothing for this limit.
- **startup_failure is collateral damage.** When the window's budget is blown, _any_ run dispatched in it is blocked, including unrelated PRs and master pushes. The stacked-PRs warning in `CLAUDE.md` describes exactly this; the Jul 6 data confirms it empirically.
- **The merge queue is not enabled.** Master branch rules include `pull_request`, `required_status_checks`, and `workflows`, but no merge queue rule, even though 23 workflows already carry `merge_group` triggers. Meanwhile every master merge triggers ~53 push workflows plus `container-images-cd.yml`, which sends 56 `repository_dispatch` calls to PostHog/charts. At 10k PRs/month (~7.5k merges), that is ~350 merge cascades on a peak day.
- **Agent/bot comment traffic is a second growth axis.** `issue_comment` (2,066/day) and review events (~2,500/day) each trigger runs (Inkeep Agent, priority-review notifications, PR canary). This scales with agent adoption independently of PR count.

### Broken observability found during this analysis

- `monitor-github-rate-limit.yml` runs successfully and logs `Emitted 14 event(s); 0 failure(s)`, but **zero `github_rate_limit_observed` events exist in the DevEx PostHog project (347861)**. The `POSTHOG_DEVEX_PROJECT_API_TOKEN` secret evidently posts to a different project (the `posthog-ci-running-time` events that do reach 347861 arrive via a separate token in `ci-backend.yml`). Until the secret and project are reconciled, the rate-limit burn alert is watching a project nobody checks.
- CI Flake Overseer (`workflow_run`-triggered) is disabled (`CI_FLAKE_OVERSEER_ENABLED` unset) and its trigger runs are themselves frequent startup_failure victims during bursts.

## Recommendations, ordered by impact

1. **Consolidate always-fire PR workflows.** ~35-46 separate runs per push is the fan-out multiplier that turns 11 simultaneous pushes into a repo-wide outage. Folding the small always-on workflows (shellcheck, pr-updated, ci-turbo, the container CD gates, etc.) into a handful of umbrella workflows with internal path-filtered jobs, or converting them to `workflow_call` reusables invoked from one parent, cuts runs-per-push several-fold. This is the only structural fix for the 500/10s cap.
2. **Add stagger tooling for stacked pushes.** The Jul 6 incident (916 runs in 20s from one restack) shows the `CLAUDE.md` guidance alone does not work. A `hogli` wrapper (or git push hook) that paces multi-branch pushes to stay under ~10 branches per 30s would eliminate the dominant burst source.
3. **Enable the merge queue.** The 23 `merge_group` workflows are already wired. A queue batches master cascades (each queue group runs CI once per batch rather than per merge) and smooths the post-merge push fan-out before merge volume grows 60%.
4. **Move the remaining big GitHub-hosted matrices to Depot.** Jest (8x `ubuntu-latest`), Storybook Chromium (16x `ubuntu-latest`), and CodeQL (5x) are the largest hosted consumers; migrating them buys back concurrent-job headroom and reduces billed hosted minutes. In parallel, ask GitHub support to raise the 500 concurrent-job cap (documented as raisable).
5. **Get cache under 10 GB.** Audit the 168 caches, shorten key retention, and move hot caches (uv, pnpm) to Depot cache on Depot-hosted jobs where it is not already used. Also shorten the two 90-day artifact retentions in `ci-backend.yml` and audit Playwright artifact sizes (30-day retention on HTML reports, screenshots, and videos).
6. **Fix the rate-limit telemetry project mismatch** so `github_rate_limit_observed` lands in DevEx (347861) where the burn-rate alert can be seen, then reconsider enabling Flake Overseer once burst noise is reduced.
7. **Open a support conversation with GitHub** about raising the trigger-event and concurrent-job limits, and about whether blocked runs (startup_failure) can degrade to queueing. Several limits on the reference page are explicitly support-raisable; the run-queue cap is the one to ask about first.

## Proposed monitoring (DevEx project 347861)

Proposals only; none of these exist yet. Data sources named per insight.

| Insight                                   | Data source                                                                                                                                 | Notes                                                                                                                         |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Run-burst pressure (startup_failures/day) | GitHub Actions API (`status=startup_failure`); needs a small scheduled emitter job, e.g. added to `monitor-github-rate-limit.yml`'s cron    | Alert on >100/day. Interim manual query in Methodology.                                                                       |
| Hosted-runner peak concurrency            | SQL insight over `posthog-ci-running-time-job` (`runner LIKE 'GitHub Actions%'`, arrayJoin minutes between `started_at` and `completed_at`) | Alert at >400 sustained. Query in Methodology.                                                                                |
| Runner minutes/day by class               | Trends/SQL over `posthog-ci-running-time-job`, `sum(duration_seconds)` split GitHub-hosted vs Depot                                         | Tracks the billing trajectory.                                                                                                |
| API rate headroom by bucket               | `github_rate_limit_observed` (blocked on the secret fix above)                                                                              | An alert on insight `iGGXQ1mF` already exists in whichever project currently receives these events.                           |
| PR/merge volume vs 10k goal               | `posthog-ci-pr-merged` events, cross-checked monthly against the GitHub search API                                                          | 9,525 events in the last 30 days vs 4,648 merged PRs in June per GitHub; reconcile before trusting either as the goal metric. |
| Cache pressure                            | `actions/cache/usage` API; same scheduled emitter as burst pressure                                                                         | Alert at >9 GB.                                                                                                               |

## Data gaps

Things this analysis could not measure from a laptop, and how to provide them:

- **Org Actions billing usage** (hosted minutes and artifact storage actuals): org Settings -> Billing & Licensing -> Usage, or `gh api /organizations/PostHog/settings/billing/usage` with an org-admin PAT.
- **Depot plan concurrency and queue times**: the depot.dev org dashboard. Depot jobs are outside GitHub's concurrency caps, but Depot has its own plan limits and its queue latency is invisible to this analysis.
- **Which project `POSTHOG_DEVEX_PROJECT_API_TOKEN` posts to**: compare the org secret's value against project API tokens (the DevEx token is committed in `hogli.yaml`).
- **GitHub's own queue-time percentiles**: org Insights -> Actions performance metrics, as an independent check on the concurrency conclusion.

## Methodology

Volume and burst measurements (GitHub API via `gh`):

```bash
# PR volume
gh api 'search/issues?q=repo:PostHog/posthog+type:pr+created:2026-06-01..2026-06-30' -q .total_count
gh api 'search/issues?q=repo:PostHog/posthog+type:pr+merged:2026-06-01..2026-06-30' -q .total_count

# Run volume (month, single day, by trigger)
gh api 'repos/PostHog/posthog/actions/runs?created=2026-06-01..2026-06-30&per_page=1' -q .total_count
gh api 'repos/PostHog/posthog/actions/runs?event=pull_request&created=2026-07-06&per_page=1' -q .total_count

# startup_failure counts and samples
gh api 'repos/PostHog/posthog/actions/runs?status=startup_failure&created=2026-07-01..2026-07-07&per_page=1' -q .total_count
gh api 'repos/PostHog/posthog/actions/runs?status=startup_failure&per_page=100' \
  -q '.workflow_runs[] | [.created_at, .event, .name] | @tsv'

# Burst measurement (second-granularity created windows work)
gh api 'repos/PostHog/posthog/actions/runs?created=2026-07-06T18:01:00Z..2026-07-06T18:01:20Z&per_page=1' -q .total_count

# Cache usage and org plan
gh api repos/PostHog/posthog/actions/cache/usage
gh api orgs/PostHog -q '.plan'
```

Concurrency and minutes (HogQL against DevEx project 347861; `posthog-ci-running-time-job` is emitted by Backend CI, Frontend CI, Storybook, and E2E Playwright only, so results are a lower bound). GitHub-hosted jobs report `runner` as `GitHub Actions <n>`, Depot jobs as `depot-<id>`; skipped/cancelled jobs have no runner:

```sql
-- Peak per-minute GitHub-hosted concurrency
SELECT minute, count() AS concurrent
FROM (
    SELECT arrayJoin(arrayMap(
        i -> toStartOfMinute(toDateTime(properties.started_at)) + toIntervalMinute(i),
        range(0, toInt(greatest(dateDiff('minute', toDateTime(properties.started_at), toDateTime(properties.completed_at)), 0)) + 1)
    )) AS minute
    FROM events
    WHERE event = 'posthog-ci-running-time-job'
      AND timestamp >= now() - INTERVAL 3 DAY
      AND properties.runner LIKE 'GitHub Actions%'
)
GROUP BY minute ORDER BY concurrent DESC LIMIT 10

-- Daily runner minutes by class
SELECT toDate(timestamp) AS day,
       round(sumIf(properties.duration_seconds, properties.runner LIKE 'GitHub Actions%') / 60) AS github_hosted_minutes,
       round(sumIf(properties.duration_seconds, properties.runner LIKE 'depot-%') / 60) AS depot_minutes
FROM events
WHERE event = 'posthog-ci-running-time-job' AND timestamp >= now() - INTERVAL 8 DAY
GROUP BY day ORDER BY day DESC
```

Live GITHUB_TOKEN limits were read from a `monitor-github-rate-limit.yml` run log (`gh run view <id> --log`), which polls `/rate_limit` from inside a workflow and therefore sees the real per-repo buckets (core 30,000/hr observed).
