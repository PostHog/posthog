# CI: things already tried

This file answers one question. **You have an idea for CI or the dev environment. Did someone try it before?**

Most of the ideas here are good ideas. People tried them because they sounded correct.
This file records the part that costs the most to find again. It records what happened when someone built the idea, and why the result did not agree with the proposal.

## How to use this file

Search before you build.

```bash
rg -i "xdist|parallel" docs/internal/ci-things-already-tried.md
```

Each entry has the title of the **proposal**. The title uses the words that a person uses to propose the idea.
The title does not use the symptom that appeared later.
Each entry ends with _Also asked as_. This line gives other words for the same idea, so that a different search finds the entry.

**A verdict is not a prohibition.** Each entry gives the date and the specific reason for the result.
Read the reason. Then examine if the reason is still correct. Runner sizes, prices, and tools change.
If the reason is no longer correct, write this in the PR and try the idea again.

## Verdicts

| Verdict      | Meaning                                                         |
| ------------ | --------------------------------------------------------------- |
| `rejected`   | Someone built the idea and measured it. The result was too bad. |
| `reverted`   | The change went to master. Then someone removed it.             |
| `superseded` | The problem was real. A different solution replaced this one.   |
| `abandoned`  | Someone started the work and stopped. There is no verdict.      |
| `open`       | The idea is good. The work is incomplete. You can continue it.  |

## Add an entry

Add an entry when you close a PR and do not merge it. Add an entry when you revert a change.
Give the entry the title of the idea. Then give the verdict, the date, and the measurement.
An entry of five lines has more value than a design document that nobody opens.

---

## Test parallelism and sharding

### Run pytest-xdist inside the backend CI shards

**Verdict: rejected** · Oct 2025 · [#38927](https://github.com/PostHog/posthog/pull/38927)

The test used 53 shards and `-n 4`.
Wall time decreased from approximately 15 minutes to approximately 9 minutes. This is a speed increase of 42.8%, and the measurement is statistically strong.
CPU cost increased from 1,572 to 3,908 core-minutes. This is a factor of approximately 2.5.

The speed increase is real. The cost is the problem.
A factor of 2.5 in compute is too much for 3 minutes of wall time.

`pytest-xdist` is still a development dependency, and it operates correctly on a local machine. CI does not use it in the shards.

_Also asked as:_ parallelize tests within a shard, `-n auto`, use the idle cores on the runner, why is each shard single-process

### Shard the Playwright E2E suite

**Verdict: reverted** · Feb 2026 · [#46774](https://github.com/PostHog/posthog/pull/46774), reverted by [#46853](https://github.com/PostHog/posthog/pull/46853)

The change added four shards. The purpose was a smaller retry set for unreliable tests.

The setup cost of each shard is the item that the proposal did not include. Each shard needs approximately 7.5 minutes of setup. The migrations alone need 3 minutes.

All 110 tests complete in approximately 4 minutes with 6 workers.
Thus four shards used approximately 22 more minutes of CPU in each run, and decreased wall time by approximately 3 minutes.

A shard retry also repeats the 7.5 minutes of setup. Thus a retry of one shard is not much faster than a retry of all the tests.

The workflow contains a comment about this decision. Read the comment near `runs-on` in `.github/workflows/ci-e2e-playwright.yml`.

_Also asked as:_ split the E2E tests across runners, parallelize Playwright, reduce flaky retry scope by sharding

### Use Bazel to scope product tests

**Verdict: abandoned** · Dec 2025 to Mar 2026 · [#43397](https://github.com/PostHog/posthog/pull/43397)

Each product could select Bazel targets. Then a change to one product could skip the legacy pytest jobs.

The branch became inactive, and the stale bot closed it. Nobody measured the result. Thus this entry is not evidence against Bazel.

A different solution achieved the same goal. The product tests moved to Turborepo in [#46971](https://github.com/PostHog/posthog/pull/46971). File-level backend selection came later.

_Also asked as:_ Bazel, build graph for test selection, only run tests for the product I changed

## Test selection

### Exclude `products/**/backend/**` from the backend paths filter

**Verdict: reverted** · Mar 2026 · [#50137](https://github.com/PostHog/posthog/pull/50137), reverted by [#50181](https://github.com/PostHog/posthog/pull/50181)

The filter gave the decision to `contract-check`. `contract-check` decides if the Django tests are necessary for a change in a product.

This assumes that the products are isolated. Most products were not isolated.
Core code imports product views, serializers, and models directly. It imports them through `posthog/api/__init__.py`, `posthog/tasks/`, and the migrations.
`contract-check` examines only the facade files. Thus it cannot see these imports.

The rule is general. A path filter that skips tests makes a statement about the import graph. Examine the import graph before you make the statement.

_Also asked as:_ narrow the backend paths filter, skip Django tests for product-only changes, trust contract-check

### Certify a facade with its `__all__`

**Verdict: superseded** · Jul 2026 · [#71127](https://github.com/PostHog/posthog/pull/71127), replaced by [#71486](https://github.com/PostHog/posthog/pull/71486)

The detector read `__all__` to prove that a facade does not re-export internal names.

Two problems stopped it. Each review round found a new gap in the detector.
Also, most facade modules do not declare `__all__`. Thus the detector could certify only the part of the surface that the module declares.

The replacement puts the rule in `products/architecture.md`. It also makes the `contract-check` inputs narrow or absent, instead of a list of file globs.

_Also asked as:_ detect facade leaks, check `__all__`, verify a product is really isolated

### Select tests from pytest-testmon coverage data

**Verdict: superseded** · Apr 2026 · [#56370](https://github.com/PostHog/posthog/pull/56370)

This PR collected the data. It did not connect the selection to CI.
The merge of 52 shard artifacts gave a map of 28,322 tests over 3,691 production files. The map has approximately 1.3 million entries.

The selectivity was high. One changed file caused a median of 45 tests. This is a skip rate of 99.8%.

Two results have more importance than these numbers.
First, there were no stale tests with high confidence. Thus a cleanup from this data had nothing to delete.
Second, 1,020 tests appeared to touch no production code. Almost all of these results are false. They come from code with many mocks, from property-based tests, and from tests of migration rules. Testmon cannot trace these paths.

Backend test selection came later from a different mechanism. Read [#85530](https://github.com/PostHog/posthog/pull/85530) and [#88265](https://github.com/PostHog/posthog/pull/88265).

_Also asked as:_ coverage-based test selection, testmon, find stale tests from coverage, only run affected tests

### Disable the pytest `unraisableexception` and `threadexception` plugins

**Verdict: open, and approved** · Jul 2026 · [#70886](https://github.com/PostHog/posthog/pull/70886)

Each pytest session runs several full-heap `gc.collect()` passes at cleanup.
These plugins run the passes only to report `__del__` exceptions and thread exceptions as warnings.
`addopts` already sets `-p no:warnings`. Thus these warnings cannot become failures, and the passes give no value.

A fixed benchmark of 320 tests decreased from 24.7 seconds to 21.8 seconds.

A reviewer approved the PR. The branch then became inactive, and the stale bot closed it.
You can open this PR again without changes.

Read this entry before you try a different solution for the pytest cleanup cost.
[#88759](https://github.com/PostHog/posthog/pull/88759) tried a different solution. It deleted the `gc.unfreeze()` in `pytest_unconfigure`.
That call is necessary. [#62707](https://github.com/PostHog/posthog/pull/62707) added it after the Temporal shards stopped with a segmentation fault and exit code 139. CI made the same crash again on #88759.
Frozen objects do not get the final cyclic collections of `Py_FinalizeEx`. Thus their finalizers run late in the teardown, after Python removes the extension modules.

_Also asked as:_ pytest teardown is slow, reduce gc.collect at session end, speed up pytest cleanup, why does the shard hang after the tests pass

## Docker and image builds

### Apply BuildKit cache mounts to the Dockerfile

**Verdict: rejected** · Oct 2025 · [#39700](https://github.com/PostHog/posthog/pull/39700)

The change added cache mounts for apt, pip, uv, node, and Playwright. It followed the documented guidance from Depot.

A measurement against master with a warm cache showed a slower build.
A backend change increased from 52.7 to 57.5 seconds. This is approximately 9% slower. A frontend change increased from 55.5 to 62.2 seconds. This is approximately 12% slower.

The workload is the reason. A cache mount adds 5 to 7 seconds of overhead, even when the cache has the data. A cache mount gives a benefit only when the dependencies change.
Approximately 95% of PRs change code and do not change dependencies. Thus the change made the frequent case slower to make the rare case faster.

_Also asked as:_ `--mount=type=cache`, speed up Docker builds, follow Depot cache best practices

### Move the source COPY to the end of the Dockerfile

**Verdict: rejected** · Oct 2025 · [#39695](https://github.com/PostHog/posthog/pull/39695)

The source COPY was already at the end. The layer order in the Dockerfile was already correct. Thus the change did nothing.

Remember this type of proposal. Examine the current state before you optimize it.

_Also asked as:_ improve Docker layer caching, reorder Dockerfile layers

### Examine the Docker Hub credentials when CI reports a pull rate limit

**Verdict: the cause was different** · Aug 2026 · [#81963](https://github.com/PostHog/posthog/pull/81963)

CI failed with this message: `toomanyrequests: You have reached your unauthenticated pull rate limit`.
At the maximum, this failure occurred in approximately 45% of the backend CI jobs. The usual rate is zero.

The message indicates an authentication problem. This is why the diagnosis took a long time.
`docker login` was successful during all of this period, and the message `Login Succeeded` was correct.

The true cause was a lapse in the Docker Hub subscription. A lapsed plan removes the entitlement. Docker then issues anonymous tokens for the pulls, but it continues to accept the login.

If you see this message again, examine the subscription status before you change the secrets.

_Also asked as:_ Docker Hub rate limit in CI, unauthenticated pull limit, DOCKERHUB secret is wrong

## CI orchestration

### Skip Storybook and E2E for snapshot-only commits from the bot

**Verdict: reverted** · Mar 2026 · [#49997](https://github.com/PostHog/posthog/pull/49997), reverted by [#51212](https://github.com/PostHog/posthog/pull/51212)

The change went to master. One week later, a revert removed it.

_Also asked as:_ skip CI for snapshot commits, ignore bot commits in CI, don't rerun visual tests for the snapshot bot

### Force-cancel the backend CI run when pytest does not stop

**Verdict: reverted** · Apr 2026 · [#54261](https://github.com/PostHog/posthog/pull/54261), reverted by [#54685](https://github.com/PostHog/posthog/pull/54685)

The change added a watchdog job. The job cancels a run when pytest does not exit.
The change stayed in master for one day.

_Also asked as:_ cancel watchdog, kill hung CI jobs, pytest ignores SIGTERM

### Add a CI step that asks a person to take a bot PR

**Verdict: rejected** · Jun 2026 · [#62111](https://github.com/PostHog/posthog/pull/62111)

CI cannot assign a PR from a bot automatically, because the bot account is not a member of the team.
The CI step asked a person to take the PR.

A different solution replaced it. A CI step must guess which person controls a bot PR.
The agent that opens the PR already knows this person. Thus the instruction moved to the PR template.

_Also asked as:_ auto-assign bot PRs, find the human behind an agent PR, nudge for ownership

## Dev environment

### Run a dmypy daemon for fast local type checks

**Verdict: rejected** · Oct 2025 · [#39319](https://github.com/PostHog/posthog/pull/39319)

A pre-commit hook used the daemon if the daemon was already active. A warm daemon gives a check of approximately 0.6 to 1.7 seconds.

The warm-up time did not decrease. Thus the first check still has the full cost.
A start of the daemon from mprocs was also tested. The commits then stopped and waited, because the daemon was still warm.

_Also asked as:_ dmypy, speed up mypy locally, type-check on commit, mypy daemon

### Run `uv sync` at each flox re-activation

**Verdict: rejected** · Feb 2026 · [#49183](https://github.com/PostHog/posthog/pull/49183)

The shell profiles synchronize the dependencies at each start of a shell. This needs approximately 660 ms when the dependencies are current.

The reason for the rejection is the frequency. The profiles also run in subshells. Thus the cost occurs much more frequently than the problem.

_Also asked as:_ auto-sync deps, keep the venv current automatically, uv sync in the shell profile

### Upgrade Python to a version that the flox uv cannot install

**Verdict: reverted** · Oct 2025 · [#40286](https://github.com/PostHog/posthog/pull/40286), reverted by [#40290](https://github.com/PostHog/posthog/pull/40290)

Python 3.12.12 needs uv 0.9.2 or later. Flox pinned uv 0.8.23, and that version can get Python 3.12.10 at the maximum.
Thus a person without Python 3.12.12 on the local machine could not build the environment.

Remember the constraint, not the versions. The repository now uses Python 3.13.13, and this pin is obsolete.
Before you increase the Python version, examine which versions the pinned flox uv can get.

_Also asked as:_ bump Python, upgrade the interpreter, why is Python pinned to an exact version

### Replace Unit and Uvicorn with Granian in one step

**Verdict: superseded** · Oct 2025 · [#40450](https://github.com/PostHog/posthog/pull/40450), replaced by [#40847](https://github.com/PostHog/posthog/pull/40847)

A dual-mode PR replaced the direct exchange. The dual mode keeps Unit as the default and starts Granian when `USE_GRANIAN=true`.
The work is the same, and the rollout is safer. Granian is a dependency today.

_Also asked as:_ migrate to Granian, replace Nginx Unit, unify the ASGI server

### Change the object storage service from MinIO to SeaweedFS

**Verdict: shipped, after several unsuccessful attempts** · first attempt Mar 2026 · [#49827](https://github.com/PostHog/posthog/pull/49827)

Other people made earlier attempts, and those attempts also failed.
The change is complete now. The dev stack and CI use SeaweedFS for both S3-compatible stores. `AGENTS.md` prohibits new dependencies on MinIO.

This entry is evidence that a migration can be correct after several failures.

_Also asked as:_ remove MinIO, SeaweedFS, replace the object storage container

## Product isolation

### Use `logs` as the first product behind a facade

**Verdict: superseded** · Jun 2026 · [#63184](https://github.com/PostHog/posthog/pull/63184)

`logs` was the first candidate for the field test. Core imports its models, its query runner, its celery task, and its temporal wiring. Thus `logs` is a difficult example.

The field test moved to `web_analytics` in [#63535](https://github.com/PostHog/posthog/pull/63535). [#63193](https://github.com/PostHog/posthog/pull/63193) collected the tools and the skill.
The note at the closure says that the tools can isolate `logs` quickly, if the team still wants this.
The doctrine from this work came later, in [#71486](https://github.com/PostHog/posthog/pull/71486).

_Also asked as:_ which product should we isolate first, facade migration example, isolate logs

## PR structure

### Put two closely coupled layers in two stacked PRs

**Verdict: rejected for this change** · Aug 2026 · [#87643](https://github.com/PostHog/posthog/pull/87643), merged into [#87644](https://github.com/PostHog/posthog/pull/87644)

The two layers read well as two stories. They did not work as two diffs.
Both layers changed the same four modules, and sometimes the same lines.
The upper layer deleted a block that the lower layer corrected. It also changed the signature of a function that the lower layer divided.

Each correction in the lower layer needed a repeat through these collisions. The repeat occurs again at each restack.

Divide a change by its diff surface, not by its story. If two layers touch the same lines, one PR needs less review effort than two.

_Also asked as:_ should I stack these, split this PR, break the change into reviewable layers
