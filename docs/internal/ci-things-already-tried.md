# CI: things already tried

A lookup list for one question: **someone has an idea for CI or the dev environment. Was it already tried?**

Most CI ideas here are good ideas. They were tried because they sounded right.
The value of this file is the part that is expensive to rediscover: what happened when someone actually built it, and why the result did not match the pitch.

## How to use this

Search before you build, not after.

```bash
rg -i "xdist|parallel" docs/internal/ci-things-already-tried.md
```

Entries are titled as the **proposal**, in the words someone would use to propose it.
They are not titled by the symptom that eventually showed up.
Each entry ends with _Also asked as_, which exists so a grep for different wording still lands.

**A verdict is not a ban.** Every entry carries the date and the specific reason it failed.
Read the reason and check whether it still holds. Runner sizes, prices, and tooling all move.
If the blocker is gone, say so in the PR and try again.

## Verdicts

| Verdict      | Meaning                                               |
| ------------ | ----------------------------------------------------- |
| `rejected`   | Built and measured. The result did not justify it.    |
| `reverted`   | Shipped to master, then pulled back out.              |
| `superseded` | The problem was real. A different approach solved it. |
| `abandoned`  | Started, never finished. No verdict was ever reached. |
| `open`       | Good idea, still unfinished. Worth picking up.        |

## Adding an entry

Add one when you close a PR without merging it, or when you revert something.
Title it as the idea. State the verdict, the date, and the measurement.
One entry, five lines, is worth more than a design doc nobody opens.

---

## Test parallelism and sharding

### Run pytest-xdist inside the backend CI shards

**Verdict: rejected** · Oct 2025 · [#38927](https://github.com/PostHog/posthog/pull/38927)

Measured across 53 shards with `-n 4`.
Wall time fell from about 15 minutes to about 9, a 42.8% speedup that was statistically solid.
CPU cost rose from 1,572 to 3,908 core-minutes, about 2.5x.

The speedup was real. The price was the problem.
Buying wall-clock with a 2.5x compute multiplier did not clear the bar.

`pytest-xdist` is still a dev dependency, so it works locally. It is not wired into the CI shards.

_Also asked as:_ parallelize tests within a shard, `-n auto`, use the idle cores on the runner, why is each shard single-process

### Shard the Playwright E2E suite

**Verdict: reverted** · Feb 2026 · [#46774](https://github.com/PostHog/posthog/pull/46774), reverted by [#46853](https://github.com/PostHog/posthog/pull/46853)

Four shards were added to narrow the retry scope for flaky tests.
The setup cost per shard was the thing that was missed: about 7.5 minutes, of which migrations alone are 3 minutes.

All 110 tests run in about 4 minutes with 6 workers.
So 4 shards spent roughly 22 extra minutes of CPU per run to save about 3 minutes of wall clock.

Retrying a shard also replays the 7.5 minute setup, so a "fast" shard retry was not much faster than rerunning everything.

The workflow still carries an inline note pointing at this decision. See the `runs-on` comment in `.github/workflows/ci-e2e-playwright.yml`.

_Also asked as:_ split the E2E tests across runners, parallelize Playwright, reduce flaky retry scope by sharding

### Use Bazel to scope product tests

**Verdict: abandoned** · opened Dec 2025, closed Mar 2026 · [#43397](https://github.com/PostHog/posthog/pull/43397)

Products would opt into Bazel targets so a product-only change could skip the legacy pytest jobs.
The branch went stale and was closed without a verdict, so this is not evidence that Bazel cannot work.

The same goal was met another way. Product tests moved to Turborepo in [#46971](https://github.com/PostHog/posthog/pull/46971), and file-level backend selection followed later.

_Also asked as:_ Bazel, build graph for test selection, only run tests for the product I changed

## Test selection

### Exclude `products/**/backend/**` from the backend paths filter

**Verdict: reverted** · Mar 2026 · [#50137](https://github.com/PostHog/posthog/pull/50137), reverted by [#50181](https://github.com/PostHog/posthog/pull/50181)

The filter left product backend changes to `contract-check`, which decides whether Django tests are needed.

That assumed products are isolated. Most were not.
Core code imports product views, serializers, and models directly, through `posthog/api/__init__.py`, `posthog/tasks/`, and migrations.
`contract-check` only watches facade files, so it could not see those crossings.

The lesson generalizes: a path filter that skips tests is a claim about the import graph. Check the graph before making the claim.

_Also asked as:_ narrow the backend paths filter, skip Django tests for product-only changes, trust contract-check

### Certify a facade by reading its `__all__`

**Verdict: superseded** · Jul 2026 · [#71127](https://github.com/PostHog/posthog/pull/71127), replaced by [#71486](https://github.com/PostHog/posthog/pull/71486)

The detector tried to prove a facade does not re-export internals by inspecting `__all__`.

Two things broke it. The detector grew a new hole in every review round.
More basically, most facade modules declare no `__all__` at all, so it could only ever certify the part of the surface that was advertised.

The replacement writes the rule into `products/architecture.md` and makes `contract-check` inputs narrow-or-nothing instead of a per-file glob list.

_Also asked as:_ detect facade leaks, check `__all__`, verify a product is really isolated

### Select tests from pytest-testmon coverage data

**Verdict: superseded** · Apr 2026 · [#56370](https://github.com/PostHog/posthog/pull/56370)

This collected the data rather than wiring the selection.
52 shard artifacts were merged into a map of 28,322 tests over 3,691 production files, about 1.3M mappings.

The selectivity was strong: a single changed file triggered a median of 45 tests, a 99.8% skip rate.

Two findings matter more than the numbers.
There were no high-confidence stale tests, so a testmon-driven cleanup had nothing to delete.
And 1,020 tests appeared to touch no production code, but nearly all were false positives from mock-heavy async code, property-based tests, and migration-rule tests. Testmon cannot trace through those.

Backend test selection later shipped from a different mechanism. See [#85530](https://github.com/PostHog/posthog/pull/85530) and [#88265](https://github.com/PostHog/posthog/pull/88265).

_Also asked as:_ coverage-based test selection, testmon, find stale tests from coverage, only run affected tests

### Disable pytest's `unraisableexception` and `threadexception` plugins

**Verdict: open, and already approved** · Jul 2026 · [#70886](https://github.com/PostHog/posthog/pull/70886)

Every pytest session pays several full-heap `gc.collect()` passes at cleanup.
Those plugins run them only to report `__del__` and thread exceptions as warnings.
`addopts` already sets `-p no:warnings`, so those warnings can never become failures. The passes are pure teardown cost.

Measured on a fixed 320-test benchmark: 24.7s to 21.8s.

The PR was reviewed and approved. It then went stale and closed without merging.
It is worth reopening as-is.

This is the entry to read before reaching for a different fix to pytest teardown cost.
A related attempt in [#88759](https://github.com/PostHog/posthog/pull/88759) tried to reorder a GC freeze around the same cost, by deleting the `gc.unfreeze()` in `pytest_unconfigure`.
That unfreeze is not incidental. It was added in [#62707](https://github.com/PostHog/posthog/pull/62707) after the Temporal shards segfaulted with exit 139, and CI reproduced the same crash on #88759.
Frozen objects skip the final cyclic collections of `Py_FinalizeEx`, so their finalizers run in late teardown, after extension modules are gone.

_Also asked as:_ pytest teardown is slow, reduce gc.collect at session end, speed up pytest cleanup, why does the shard hang after tests pass

## Docker and image builds

### Apply BuildKit cache mounts to the Dockerfile

**Verdict: rejected** · Oct 2025 · [#39700](https://github.com/PostHog/posthog/pull/39700)

Cache mounts were added for apt, pip, uv, node, and Playwright, following Depot's published guidance.

Measured against master with a warm cache, it was slower.
Backend changes went from 52.7s to 57.5s, about 9% slower. Frontend changes went from 55.5s to 62.2s, about 12% slower.

The reason is workload shape. Cache mounts add 5 to 7 seconds of overhead even on a hit, and they only pay off when dependencies change.
About 95% of PRs change code, not dependencies. So the change taxed the common case to speed up the rare one.

_Also asked as:_ `--mount=type=cache`, speed up Docker builds, follow Depot cache best practices

### Move source COPY to the end of the Dockerfile

**Verdict: rejected** · Oct 2025 · [#39695](https://github.com/PostHog/posthog/pull/39695)

It was already there. The Dockerfile's layer order was already correct, so the change was a no-op.

Worth remembering as a class of idea: confirm the current state before optimizing it.

_Also asked as:_ improve Docker layer caching, reorder Dockerfile layers

### Chase Docker Hub credentials when CI hits pull rate limits

**Verdict: superseded by the real cause** · Aug 2026 · [#81963](https://github.com/PostHog/posthog/pull/81963)

CI failed with `toomanyrequests: You have reached your unauthenticated pull rate limit`.
At peak this hit roughly 45% of backend CI jobs, against a baseline of zero.

The message points at authentication, and that is what made it expensive.
`docker login` succeeded the whole time, and `Login Succeeded` was accurate.

The actual cause was a Docker Hub **billing lapse**. A lapsed plan removes entitlement, so Docker issues anonymous-class pull tokens while still accepting the login.

If this wording appears again, check the plan status before re-plumbing secrets.

_Also asked as:_ Docker Hub rate limit in CI, unauthenticated pull limit, DOCKERHUB secret is wrong

## CI orchestration

### Skip Storybook and E2E on bot snapshot-only commits

**Verdict: reverted** · Mar 2026 · [#49997](https://github.com/PostHog/posthog/pull/49997), reverted by [#51212](https://github.com/PostHog/posthog/pull/51212)

Shipped, then pulled back a week later.

_Also asked as:_ skip CI for snapshot commits, ignore bot commits in CI, don't rerun visual tests for the snapshot bot

### Force-cancel backend CI when pytest hangs on cancellation

**Verdict: reverted** · Apr 2026 · [#54261](https://github.com/PostHog/posthog/pull/54261), reverted by [#54685](https://github.com/PostHog/posthog/pull/54685)

A watchdog job was added to force-cancel a run when pytest would not exit.
It lasted one day.

_Also asked as:_ cancel watchdog, kill hung CI jobs, pytest ignores SIGTERM

### Add a CI step that nudges humans to self-assign on bot PRs

**Verdict: rejected** · Jun 2026 · [#62111](https://github.com/PostHog/posthog/pull/62111)

Bot-authored PRs cannot be auto-assigned, since the bot account is not a team member.
A CI step tried to nudge a human into claiming them.

It was dropped for a lighter approach. A CI step has to guess who is behind a bot PR.
The agent opening the PR already knows, so the guidance moved into the PR template instead.

_Also asked as:_ auto-assign bot PRs, find the human behind an agent PR, nudge for ownership

## Dev environment

### Run a dmypy daemon for fast local type checking

**Verdict: rejected** · Oct 2025 · [#39319](https://github.com/PostHog/posthog/pull/39319)

A pre-commit hook used the daemon when it was already running, giving roughly 0.6 to 1.7s checks once warm.

The warm-up never got cheaper, so the first check still paid full cost.
Starting the daemon from mprocs was tried too, and then commits hung while the daemon was still warming.

_Also asked as:_ dmypy, speed up mypy locally, type-check on commit, mypy daemon

### Run `uv sync` on every flox re-activate

**Verdict: rejected** · Feb 2026 · [#49183](https://github.com/PostHog/posthog/pull/49183)

Shell profiles would sync dependencies on every shell start, about 660ms when already current.

It was dropped as trying too hard. Profiles run in subshells too, so the cost is paid far more often than the problem occurs.

_Also asked as:_ auto-sync deps, keep the venv current automatically, uv sync in the shell profile

### Upgrade Python past what flox's uv can install

**Verdict: reverted** · Oct 2025 · [#40286](https://github.com/PostHog/posthog/pull/40286), reverted by [#40290](https://github.com/PostHog/posthog/pull/40290)

3.12.12 needs uv 0.9.2 or newer. Flox pinned uv 0.8.23, which could only fetch up to 3.12.10.
Anyone without 3.12.12 already installed could not build the environment.

The constraint is the shape to remember, not the versions. The repo is now on 3.13.13, so this specific pin is long gone.
Before bumping Python, check what the flox-pinned uv can actually fetch.

_Also asked as:_ bump Python, upgrade the interpreter, why is Python pinned to an exact version

### Replace Unit and Uvicorn with Granian everywhere at once

**Verdict: superseded** · Oct 2025 · [#40450](https://github.com/PostHog/posthog/pull/40450), replaced by [#40847](https://github.com/PostHog/posthog/pull/40847)

The straight swap was closed for a dual-mode version that defaults to Unit and enables Granian behind `USE_GRANIAN=true`.
Same work, safer rollout. Granian is a dependency today.

_Also asked as:_ migrate to Granian, replace Nginx Unit, unify the ASGI server

### Swap the object storage service from MinIO to SeaweedFS

**Verdict: eventually shipped, after several failed attempts** · first attempt Mar 2026 · [#49827](https://github.com/PostHog/posthog/pull/49827)

Worth knowing that earlier attempts by other people also failed before this one.
It has since landed. Both S3-compatible stores in the dev and CI stack are SeaweedFS now, and `AGENTS.md` treats new MinIO dependencies as off-limits.

Read this entry as evidence that a repeatedly failed migration can still be the right call.

_Also asked as:_ remove MinIO, SeaweedFS, replace the object storage container

## Product isolation

### Use `logs` as the first product to isolate behind a facade

**Verdict: superseded** · Jun 2026 · [#63184](https://github.com/PostHog/posthog/pull/63184)

`logs` was picked as the field test. Core imported its models, query runner, celery task, and temporal wiring, so it was a genuinely hard case.

The field test moved to `web_analytics` in [#63535](https://github.com/PostHog/posthog/pull/63535), and the tooling and skill were consolidated in [#63193](https://github.com/PostHog/posthog/pull/63193).
The note on closing was that `logs` can be re-cut from that tooling quickly if it is still wanted.
The doctrine that came out of this line of work landed later, in [#71486](https://github.com/PostHog/posthog/pull/71486).

_Also asked as:_ which product should we isolate first, facade migration example, isolate logs

## Splitting work into PRs

### Split closely coupled layers into separate stacked PRs

**Verdict: rejected for this case** · Aug 2026 · [#87643](https://github.com/PostHog/posthog/pull/87643), folded into [#87644](https://github.com/PostHog/posthog/pull/87644)

Two layers of a change read well as two stories but not as two diffs.
Both rewrote the same four modules, sometimes the same lines.
The upper layer deleted a block the lower layer was fixing, and re-signatured a function the lower layer was splitting.

Every fix had to be replayed through those collisions, and the replay repeats on each restack.

Split by diff surface, not by narrative. If two layers touch the same lines, one PR is cheaper to review than two.

_Also asked as:_ should I stack these, split this PR, break the change into reviewable layers
