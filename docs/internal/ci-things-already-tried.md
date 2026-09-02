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

## Remove an entry

Age alone is not a reason to remove an entry. The pytest-xdist entry is the oldest here, and people still propose that idea.

Remove an entry when one of these is true:

The system that it describes is gone. A person cannot propose the idea any more, so the verdict guides nobody.

The idea shipped later. The entry is history, not prior art. Keep it only when the first failure is still a trap.

The entry gives a general lesson and no specific trap. "Measure before you optimize" does not need an entry.

Give the reason when you remove an entry. Do not remove an entry because it looks old.

---

## Test parallelism and sharding

### Run pytest-xdist inside the backend CI shards

**Verdict: rejected** · Oct 2025 · [#38927](https://github.com/PostHog/posthog/pull/38927)

The test used 53 shards and `-n 4`.
Wall time decreased from approximately 15 minutes to approximately 9 minutes. The PR reports the difference as statistically strong.
CPU cost increased from 1,572 to 3,908 core-minutes. This is a factor of approximately 2.5.

The speed increase is real. The cost is the problem.
A factor of 2.5 in compute is too much for 6 minutes of wall time.

`pytest-xdist` is still a development dependency, and it operates correctly on a local machine. CI does not use it in the shards.

_Also asked as:_ parallelize tests within a shard, `-n auto`, use the idle cores on the runner, why is each shard single-process

### Change the `django_db_setup` fixture from package scope to session scope

**Verdict: rejected** · Apr 2026 · [#57030](https://github.com/PostHog/posthog/pull/57030)

Package scope builds the test database one time for each package directory. Session scope builds it one time for the whole run, which looks strictly faster.

The PR did not merge. `posthog/conftest.py` still declares `@pytest.fixture(scope="package")`.
Read [#57227](https://github.com/PostHog/posthog/pull/57227) with this one. It makes the cost of `django_db_setup` visible in the pytest output. Today that cost hides in the setup phase of the first test that pytest collects, and makes that test look slow for no reason.

Measure the setup cost first. Then you know what a scope change can win.

_Also asked as:_ session-scoped database fixture, build the test database once, why is the first test so slow

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

Backend test selection came later from a different mechanism. It uses the Snob import graph. Read the next entry.

_Also asked as:_ coverage-based test selection, testmon, find stale tests from coverage, only run affected tests

### Snob is in CI, but CI does not use it

**Verdict: CI does use it.** The scope was narrow on purpose.

`tools/snob_backend_test_selection_shadow.py` selects the Django test subset for a PR. It combines the Snob import graph with Django-aware heuristics.

Two things make this look inactive:

`pytest-snob` is an inline PEP 723 dependency of that script. It is not in `pyproject.toml`. Thus a search of the dependency file finds nothing.
The selection was also active for draft PRs only for some time. The team wanted a stable merge queue first.

[#85530](https://github.com/PostHog/posthog/pull/85530) then extended the selection to PRs that are ready for review. [#88265](https://github.com/PostHog/posthog/pull/88265) put the Django selection and the product selection in one job.
Read the comment at the top of `.github/workflows/ci-backend.yml` for the current rules.

_Also asked as:_ snob, is test selection on, why does CI run all the tests, do we select tests on PRs

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

A narrow version came later and stayed. [#42124](https://github.com/PostHog/posthog/pull/42124) added a uv cache mount, and the Dockerfile also has pnpm and npm mounts today.
That narrow version then caused its own failure. The uv cache kept wheels that were compiled against a different `libxmlsec1` version, and the build failed with a version mismatch.
[#43066](https://github.com/PostHog/posthog/pull/43066) proposed to remove the mount again. [#43091](https://github.com/PostHog/posthog/pull/43091) gave the better fix: it puts the `libxmlsec1` version in the cache ID, so a change of the system library invalidates the cache.
Read the `id=uv-libxmlsec1...` mount in the Dockerfile.

The rule: add a cache mount for one expensive step that you measured. Do not add cache mounts everywhere. Put the version of any system library that the cached artifacts compile against in the cache ID.

_Also asked as:_ `--mount=type=cache`, speed up Docker builds, follow Depot cache best practices, xmlsec version mismatch in the image build

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

### Move CI from the Depot runners to Blacksmith

**Verdict: rejected** · Apr 2026 to May 2026 · [#54559](https://github.com/PostHog/posthog/pull/54559), removed by [#57991](https://github.com/PostHog/posthog/pull/57991)

The trial did not do a direct exchange. It ran a Blacksmith shadow of most compute jobs on the same commit, behind the `BLACKSMITH_SHADOW_ENABLED` variable. Each shadow used `continue-on-error`, and no shadow was a required check.

The team kept Depot. [#57991](https://github.com/PostHog/posthog/pull/57991) removed the shadow workflow and the matrix branches.
The measurements are not in the PRs, so this entry cannot show them.
It kept `.github/scripts/compare-ci-runners.py` and marked the file as legacy. That script produced the numbers of the trial.

If you propose this again, equalize the caches of the two providers first. A runner that keeps a warm cache between jobs measures the cache, not the compute.
Run the trial for several days. A short window cannot separate the jobs whose times are close.

_Also asked as:_ change CI provider, Blacksmith, cheaper runners, are the Depot runners slow

### Use sparse-checkout on the large CI workflows

**Verdict: abandoned** · Oct 2025 · [#39239](https://github.com/PostHog/posthog/pull/39239)

The description covers the backend, frontend, and Rust workflows. The diff changes only `ci-backend.yml` and `ci-rust.yml`.

The PR did not merge, and no person reviewed it. The stale bot closed it. Thus there is no recorded reason for the result.

Sparse-checkout is correct for small jobs, and `ci-storybook.yml`, `ci-security.yaml`, and `pr-resolve-outdated-bot-comments.yml` use it today.
`ci-rust.yml` also uses it on the build and test jobs, but that came before this PR.
The large Python and frontend test jobs do not use it. Their checkout is complete.

If you propose this again, name the jobs and prove that each one reads only the included paths. A test job can read more of the tree than an exclusion list expects.

_Also asked as:_ sparse-checkout, partial clone, do not check out the whole repo, speed up the checkout step

### Jest reports the Rust snapshots as obsolete

**Verdict: superseded** · Jan 2026 · [#46008](https://github.com/PostHog/posthog/pull/46008)

Jest found the `.snap` files under `rust/cymbal/tests/snapshots/` during the Storybook visual regression job. It marked them as obsolete, and all 19 jobs failed.

The PR records the attempts that did not work. `modulePathIgnorePatterns` changes only the module resolution. It does not change which snapshot files Jest finds.
The PR proposed `haste.blockList`. The repository does not use that option today, so a different change solved this.

Keep the record: the snapshot scan and the module resolution use different configuration.

_Also asked as:_ obsolete snapshots in CI, Jest finds rust snapshots, modulePathIgnorePatterns

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

### Share the dev environment and the Docker containers across worktrees

**Verdict: three attempts, none merged** · Oct 2025 to Apr 2026 · [#40634](https://github.com/PostHog/posthog/pull/40634), [#45984](https://github.com/PostHog/posthog/pull/45984), [#51100](https://github.com/PostHog/posthog/pull/51100)

Each attempt used a different mechanism.
[#40634](https://github.com/PostHog/posthog/pull/40634) changed the compose setup so a worktree uses the containers of the main checkout.
[#45984](https://github.com/PostHog/posthog/pull/45984) set `COMPOSE_PROJECT_NAME` in the flox variables. Docker Compose uses the directory name when this variable is absent, so each worktree makes its own containers.
[#51100](https://github.com/PostHog/posthog/pull/51100) shared the flox environment, the Python virtual environment, and `node_modules`. It reports approximately 5 GB of disk for each worktree.

None of the three merged. `bin/wait-for-docker` gives the compose project the default name `posthog` today, which gives the shared containers that #45984 wanted.

Read [#40634](https://github.com/PostHog/posthog/pull/40634) first if you propose this again. It asks the question that stopped all three: does any person need separate databases for each worktree?

_Also asked as:_ worktrees start their own containers, share node_modules between worktrees, worktree disk usage, COMPOSE_PROJECT_NAME

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

## Django performance

[docs/internal/django-startup-time.md](django-startup-time.md) is the deep source for this area. It has a Traps section that records the failure modes of each mechanism.
The entries below give the proposals that people repeat.

### Squash the Django migration history

**Verdict: rejected** · Feb 2026 to Mar 2026 · [#48267](https://github.com/PostHog/posthog/pull/48267)

The PR added a squash planner, a policy for opaque operations, and 65 squashed migrations across the historical range. A zero-to-head migration on a fresh database was successful, and the schema comparison found no structural difference.

The problem is the value. The PR reports that the effect on the timing was small and noisy. The work to resolve each blocker is large, and the reviews are difficult.

[#60518](https://github.com/PostHog/posthog/pull/60518) tried a second angle three months later. It took the final project state at a cutoff date and rebuilt it as one set of `CreateModel` operations. The PR says that per-app squashing "only nibbles at it because the dep graph is cross-app". That PR also did not merge.

The migration replay in CI is a real cost. Two different squash designs did not decrease it enough. A different change must decrease it.

_Also asked as:_ squash the migrations, compress the migration history, why are there so many migrations, speed up the migration replay, nextgensquash

### Build the generated pydantic schema lazily with `defer_build`

**Verdict: reverted** · [docs/internal/django-startup-time.md](django-startup-time.md)

This removed approximately 400 ms of core-schema construction from each `django.setup()`. The round-trip tests were all successful.

Two problems stopped it. First, the deferred builds move to the first `/query` of each web worker after a deploy. A warm-up loop for those builds measured approximately 2.5 times more expensive than the eager construction.
Second, the query runners construct the response models directly. This does no validation, so it does not start the lazy build. `model_dump()` then sends a mock serializer into pydantic-core and raises `TypeError: 'MockValSer' object cannot be converted to 'SchemaSerializer'`. This is a 500 error in any process.

A different solution removed the cost. `django.setup()` no longer imports `posthog.schema` at all.

_Also asked as:_ `defer_build`, make the schema import lazy, pydantic model build is slow at startup

### Replace pydantic in the generated schema with plain dataclasses

**Verdict: not viable today**

`posthog/schema.py` has more than 1,000 generated classes. `hogli build:schema` generates the file from the TypeScript types with pydantic tooling.
Approximately 220 files call `model_validate`, and more call the `model_validate_json` and `model_validate_python` variants. The API layer depends on this validation. Thus a change of the model library is not a local change.

The import cost is solved. `posthog.schema` costs approximately 2 seconds to import, but `django.setup()` no longer loads it. The enums also moved to `posthog.schema_enums`, which imports in approximately 20 ms.
Import a model from `posthog.schema` inside the method that uses it. Take the enums from `posthog.schema_enums`.

_Also asked as:_ remove pydantic, use dataclasses for the schema, the schema import is slow, why is `posthog.schema` so big

## Database migrations

### Switch the Person model to the partitioned table with a Django setting

**Verdict: eight attempts closed unmerged** · Nov 2025 · [#41436](https://github.com/PostHog/posthog/pull/41436), [#41513](https://github.com/PostHog/posthog/pull/41513), [#41522](https://github.com/PostHog/posthog/pull/41522), [#41600](https://github.com/PostHog/posthog/pull/41600), [#41604](https://github.com/PostHog/posthog/pull/41604), [#41669](https://github.com/PostHog/posthog/pull/41669), [#41698](https://github.com/PostHog/posthog/pull/41698), [#41813](https://github.com/PostHog/posthog/pull/41813)

The goal is to move the Person model from `posthog_person` to a table that is partitioned by `team_id`. Eight PRs tried five mechanisms.

A `PERSON_TABLE_NAME` setting that gives `db_table` to the model. A dual manager that reads both tables and prefers the new one. A swap of the two table names in the database. A wrapper that rejects any query to a partitioned table without `team_id` in the `WHERE` clause. A separate test database for the person tables.

None of them merged. The author wrote this on [#41513](https://github.com/PostHog/posthog/pull/41513):

> I'm still not sure if I got on the wrong track here by wanting to bend all test setup to use the person_new table and other sqlx migrated stuff. It seems I overlooked something fundamental since things are failing so much.

One narrow PR from the same window did merge. [#41620](https://github.com/PostHog/posthog/pull/41620) put `team_id` into the Person queries that lacked it, and it carried the `PERSON_TABLE_NAME` setting to master.
The setting is in `posthog/settings/data_stores.py`, and `Person.Meta.db_table` reads it. It defaults to `posthog_person`, so the cutover is off.
The switch exists. The eight PRs above failed at what surrounds it: the test setup, the dual reads, and the partition guard.
`posthog_person_new` comes from the sqlx migrations in `rust/persons_migrations/`. Three Dagster jobs read it, and one carries a comment about a future name swap.
Person and group data now goes through the gRPC client in `posthog/personhog_client/`. `AGENTS.md` makes that client the required interface and prohibits new ORM queries against the person tables.

Read this entry before you propose a Django-level cutover. The setting is already there.
What is missing is everything that must be true before a person changes its value.

_Also asked as:_ partition the person table, `PERSON_TABLE_NAME`, `posthog_person_new`, dual-table reads, cut over the Person model

## API contracts

### Validate the API responses against the generated OpenAPI schema

**Verdict: six attempts, none merged** · Mar 2026 to Jun 2026

The idea returns in two shapes.

End-to-end traffic validation, in the Playwright run. Most of these use a Django middleware, and [#49895](https://github.com/PostHog/posthog/pull/49895) uses Spectral and a Prism proxy instead: [#49898](https://github.com/PostHog/posthog/pull/49898), [#49932](https://github.com/PostHog/posthog/pull/49932), [#49940](https://github.com/PostHog/posthog/pull/49940).
Response validation inside the pytest run, with a report as a CI artifact: [#56804](https://github.com/PostHog/posthog/pull/56804), [#56810](https://github.com/PostHog/posthog/pull/56810).

Each PR made the validation optional and non-blocking, to avoid noise. None of them merged.
Read this history before you start a seventh attempt. Six PRs that all stop before the merge is a signal about the design, not about the effort.

The generated types have a different guard today. The serializers produce the OpenAPI schema, and `hogli build:openapi` generates the TypeScript from it. CI fails when the committed output does not match.

_Also asked as:_ contract testing, validate responses against the schema, spectral, prism, schema drift in CI

## Product isolation

### Move `ee/` into `products/enterprise/backend/`

**Verdict: rejected** · Nov 2025 · [#41025](https://github.com/PostHog/posthog/pull/41025)

The PR moved 613 files and kept the git history. It kept the app label `ee`, so the database did not change. Django validated, and no migration was necessary.

The PR did not merge, and `ee/` is still a top-level directory.

A mechanically correct move is not sufficient for a directory of this size. If you propose this again, say who reviews 613 moved files, and what breaks for each open PR that touches `ee/`.

_Also asked as:_ move ee to products, get rid of the ee folder, enterprise product folder

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
