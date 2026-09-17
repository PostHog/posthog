# Django-aware dependency edges for backend test selection

An experiment: can Django's own registries tell us about test dependencies that Snob's import graph cannot see, cheaply enough to use on every PR?

**Short answer.** Yes for URL routing, and the information is almost entirely new: 93% of the resolver-derived edges join a test to a view file the test never imports.
The signal receiver registry is also real information. The obvious way to spend it, seeding Snob with the file on the other side of each connection, made selection about 2.5x _larger_ on the median signal-connected file, so it stays off.
Model relation metadata is cheap to read and near-worthless for selection.

The whole edge map costs about 76 seconds to build for this repository.
On 15 replayed master commits it changed the selected set by one test file, because the existing heuristics already over-select by so much that there is little left to find.
That is the argument against integrating it as it stands. The same edges become worth more if the blunt fallbacks they would replace are ever narrowed, which is the argument for keeping the prototype around.

Everything below is reproducible from `tools/django_edges/`.

## How an extra edge can reach Snob

`snob_lib` (the Rust extension behind `pytest-snob`) exposes exactly one function:

```python
snob_lib.get_tests(changed_files: list[str]) -> list[str]   # -> test files
```

The graph itself is internal, so an extra edge cannot be handed to Snob as an edge.
The only injection point is the changed-file set: if a Django edge says "a change to A affects B", adding B to the input makes Snob's own closure run over B as well.
That is what `tools/snob_backend_test_selection_shadow.py --django-edges` does, so the framework edges enter the existing dependency representation instead of forming a second selection mechanism next to it.

This has one consequence worth stating early, because it shapes the results: injecting at the diff catches a **changed file that itself carries an edge**.
It cannot catch a helper that only a view imports, because the edge hangs off the view, not the helper.
A real edge inside the graph would catch it, since the closure would pass through the view on the way to the test.
The fixture below demonstrates exactly that gap (`shop/pricing.py`).

The selector already has Django-flavored heuristics, all of them name- and token-based: `_is_signal_handler_file` (does the file contain `@receiver` or `*.connect`, or is "signal" in its name), `_is_middleware_file` ("middleware" in the file name), API route tokens fuzzed for plurals and dashes, and a same-directory fallback.
The experiment replaces guesses of this shape with answers from Django.

## Patterns the import graph misses

Five, ordered by how much signal they carry.

### 1. URL dispatch: a test names the route, and Django resolves the view at runtime

A test posts to `/api/projects/{team}/alerts` and never imports the viewset that serves it.
Django's resolver knows which view that path reaches. Asking it for every URL literal in every test file yields **1774 edges over 263 view and URLconf files**, and **1642 of them (93%) connect a test to a view file the test does not import** (direct imports only, so this is a conservative count of what the import graph already knows).

The shape that hurts most is a product view whose HTTP tests live outside the product tree: **103 of the 408 edges from a `products/*` view file point at a test file in another tree**, usually `posthog/api/test/`.
The existing `product_api_client:<product>` group only collects tests under `products/<product>/`, so those tests are invisible to it.

Verified example from this repository:

```text
products/alerts/backend/presentation/views/alert.py     # changed
posthog/api/test/test_alert_15_minute_interval.py:57    # self.client.post(f"/api/projects/{self.team.id}/alerts", ...)
```

The current selector does not select that test for that change. `tools/test_snob_backend_test_selection_shadow.py::test_django_url_edges_select_a_test_that_only_requests_the_route` locks in the fix.

### 2. Signal receivers in another app

`AppConfig.ready()` connects receivers, so the wiring exists only at runtime.
The live registry holds **380 receivers across 27 signal objects**, of which **261 pairs resolve to a sender model file and a receiver file in this repository**.
**105 of the 142 distinct file pairs are cross-app**, and **53 of them have no direct import in either direction**, so that much is new information.
`posthog/models/comment/comment.py` and `products/conversations/backend/signals.py` are one such pair: a soft-deleted comment updates a conversation, and neither file imports the other.

This is a precision problem rather than a recall problem, which was not what we expected going in.
All **64 files that hold a receiver with a model sender** (43 of them for a sender declared in a different file) are already detected by `_is_signal_handler_file`, so recall is covered, by selecting **every one of the 1184 API-client test files in the repository**.

### 3. `AppConfig.ready()` wiring, and files directly under an app root

Removing one line from `ShopConfig.ready()` in the fixture breaks two tests and selects none, and no edge in this prototype recovers it.

The same class of file has a second problem in the current selector. `_django_app_for_path` slices the first two path components, so for a file that sits directly under `posthog/` it returns the _file_, not a directory:

```python
_django_app_for_path("posthog/apps.py")   # -> 'posthog/apps.py'
_django_app_for_path("posthog/health.py") # -> 'posthog/health.py'
```

`_find_tests_in_app` then prefixes it with `/` and matches nothing, so the same-app fallback is a silent no-op for `posthog/apps.py`, `posthog/urls.py`, `posthog/health.py` and their neighbors.
The measured consequence is in the table below: a `posthog/urls.py` diff narrows the Django suite to two test files, and a `posthog/apps.py` diff selects nothing at all.
The app registry has the right answer (`apps.get_app_config("posthog").path`), but for this repository that answer is "the whole `posthog/` tree", which is not a useful narrowing either.
Django's app granularity is too coarse here and finer than the path for products, so the registry does not rescue the same-app idea. It only shows the bug.

### 4. Middleware known by registry, not by name

`settings.MIDDLEWARE` names 42 entries, 4 of which live in this repository.
One of them, `posthog.health.healthcheck_middleware`, the _first_ middleware in the list, is in `posthog/health.py`, which the `"middleware" in filename` rule does not match.
So a change to a file that runs on every request triggers no middleware expansion today, and, per the previous section, no same-app expansion either.

### 5. Settings-dependent behavior and second-hop framework edges

Both show up in the fixture and neither is fixable by injecting at the diff:

- `settings.py` changes the discount threshold the API test asserts. In this repository `posthog/settings/` is a `FULL_RUN_PATTERNS` entry, so the blunt instrument covers it.
- `shop/pricing.py` is imported only by the view and the receiver. Its behavior reaches both tests, and neither Snob nor the edge map selects anything, because the edges sit one hop away.

## Minimal reproduction

`tools/django_edges/fixture/` is a self-contained Django project (sqlite, three tests) whose dependencies are all framework-mediated: a receiver connected in `ready()`, a view reached only through a URL literal, a helper imported only by those two, and a settings value the assertions depend on.
It runs under its own `pytest.ini`, and the root `pytest.ini` ignores the directory, alongside the other `tools/` entries that are not part of the suite.
CI never reaches it either: the backend targets are `posthog ee/` plus the Turbo product tasks.

`tools/django_edges/fixture/demo.py --mutate` prints the comparison. Each row mutates the file's behavior, runs the three tests, and reports what each selection strategy would have run:

```text
changed file             snob  +django   fails  detail
shop/models.py              2        0       0
shop/receivers.py           0        2       1  django adds tests/test_order_api.py, tests/test_order_totals.py
shop/views.py               0        1       1  django adds tests/test_order_api.py
shop/pricing.py             0        0       2  STILL MISSED tests/test_order_api.py, tests/test_order_totals.py
shop/apps.py                0        0       1  STILL MISSED tests/test_order_totals.py
urls.py                     0        1       1  django adds tests/test_order_api.py
settings.py                 0        0       1  STILL MISSED tests/test_order_totals.py
```

Counts are test _files_; `fails` is what actually goes red.
The import graph selects both tests for `shop/models.py` and nothing for every other file in the project, including three files whose behavior two of the three tests depend on.
The Django edges close the receiver, view and URLconf rows. The last three rows are the honest limit of this approach.

The fixture also reproduces the blind spot in a second, independent tool: the `tach` pytest plugin prints `[Tach] WARNING: 2 test(s) failed that would be skipped by impact analysis!` on the receiver mutation. Both tools build import graphs, so both miss the same edge.

## The prototype

`tools/django_edges/extract.py` runs `django.setup()` and writes an edge map. Three extractors:

| Extractor | Source                                                                                                            | Output                              |
| --------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `urls`    | `get_resolver()`, then every URL literal and `reverse()` name found in test files, resolved against that resolver | view/URLconf file -> test files     |
| `signals` | `Signal.receivers` for every `Signal` instance reachable from `sys.modules`                                       | sender model file <-> receiver file |
| `models`  | `Model._meta.get_fields()` relation targets                                                                       | model file -> related model files   |

Two details that took a round to get right, both worth keeping if anyone extends this:

- **Catch-all views silently swallow everything.** This repository answers any unmatched `/api/...` path with `api_not_found`, and any unmatched non-API path with the SPA view. A naive "resolve the literal" pass therefore resolves _every_ string and attributes 348 bogus edges to `posthog/api/rest_router.py`. The extractor probes three deliberately unroutable paths at startup and discards matches to whatever answers them.
- **The URLconf file is an edge in its own right.** `include()` carries the declaring module, so editing the file that mounts a route gets the route's tests. It also creates one hub: `path("api/", include(router.urls))` means every DRF-router route is attributed to `posthog/urls.py`, which collects 578 test files. Correct, but treat it as a pattern-level signal rather than an ordinary edge.

Consumption is in `tools/snob_backend_test_selection_shadow.py`:

- `--django-edges PATH` adds a `django_url_edge:<file>` group per changed file. It only ever adds tests.
- `--django-signal-expansion` additionally seeds Snob with signal neighbors _and_ drops the blanket `signal_handler_api_tests` group. Off by default, for the reason in the next section.

Both are off in CI.

## Before and after

Measured with `tools/django_edges/measure.py`, which runs the selector twice over the same changed-file set (once as CI runs it, once with the edges) and diffs the results.
All numbers are **test files**, not test cases. This checkout has no `.test_durations` (CI generates it), so the duration columns are zero and are not quoted here.

### URL edges

263 scenarios, one changed view or URLconf file each:

|                                       | before | after                     |
| ------------------------------------- | ------ | ------------------------- |
| median selected test files            | 60     | 61                        |
| scenarios where the selection changed |        | 59 (all gains, no losses) |
| test files added                      |        | 1140                      |

576 of those 1140 come from one scenario, `posthog/urls.py`, which is the hub discussed above.
The other 564 are spread over 58 scenarios.
Largest: `posthog/api/project.py` +320 (its list endpoint is exercised from all over the suite), `posthog/frontend_views.py` +41, `posthog/api/organization.py` +22, `products/product_analytics/backend/presentation/insight_ee.py` +17, `products/feature_flags/backend/api/feature_flag.py` +14, `posthog/api/query.py` +13.

Two gains verified by hand against the test source:

```text
posthog/api/query.py            <- posthog/test/test_middleware.py:936   DELETE /api/projects/{id}/query/SomeQueryId123/
products/alerts/.../alert.py    <- posthog/api/test/test_alert_15_minute_interval.py:57   POST /api/projects/{id}/alerts
```

### Five files where the heuristics looked weak

| changed file                                       | before | after | what happens                                                                                                                                                                                                                                  |
| -------------------------------------------------- | -----: | ----: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `posthog/urls.py`                                  |      2 |   578 | Selects `posthog/test/test_urls.py` and one Snob hit. Two test files for the root URLconf, and no guard downstream catches it because the selection is not empty.                                                                             |
| `posthog/apps.py`                                  |      0 |     0 | No rule reaches it at all. `turbo-discover.js` catches the empty selection and falls back (full run when the PR is ready, skip on a draft), so nothing is silently missed. The selector contributes nothing here, and neither do these edges. |
| `posthog/health.py`                                |     67 |    67 | The conventional neighbor plus Snob's closure. The middleware expansion never fires, because the rule matches on the file name.                                                                                                               |
| `posthog/models/comment/comment.py`                |   2778 |  3142 | Signal expansion, growing the set.                                                                                                                                                                                                            |
| `posthog/caching/organization_serializer_cache.py` |   1203 |  3074 | The blanket fallback (1184 of the 1203) is replaced by an expansion over 6 neighbor files, which Snob closes over into 3074.                                                                                                                  |

The first row is the clearest recall hole this experiment found in the current selector, and the one the URL edges close outright.
Neither of the first two is a `FULL_RUN_PATTERNS` entry or in `tools/testmon_high_fanout_files.txt`.

### Signal expansion

105 scenarios, one changed signal-connected file each:

|                            | before | after |
| -------------------------- | ------ | ----- |
| median selected test files | 1242   | 3077  |
| scenarios that shrank      |        | 25    |
| scenarios that grew        |        | 65    |

The expansion is worse than the fallback it replaces. Seeding Snob with a sender model file selects everything that transitively imports that model, and the senders are `Team`, `User` and `Organization`.
Dropping the blanket fallback does not pay for that.

The registry is still useful here, just not this way. Scoping the fallback to the **app directories of the sender models** (from `model._meta.app_config.path`) instead of the whole repository gives, per receiver file:

|                                                                      | test files |
| -------------------------------------------------------------------- | ---------- |
| blanket `signal_handler_api_tests` (today)                           | 1184       |
| app-scoped, median over 64 receiver files                            | 227        |
| app-scoped, worst case (`posthog/models/signals.py`, 23 sender apps) | 819        |

A 5x narrowing on the median receiver file, with one assumption that this experiment did not test: that the tests exercising a receiver live under the sender's app or the receiver's own.
The URL data suggests caution, because cross-tree tests are common, so this wants validating against the testmon coverage data from [#56370](https://github.com/PostHog/posthog/pull/56370) before anyone ships it.

### Model relations

692 file pairs, 608 with no direct import between them. The reason is that relations are declared as strings (`ForeignKey("posthog.Team")`), and most of them point at `Team`, `User` or `Organization`.
An edge that fires on every tenant-scoped model and lands on a hub model does not narrow anything. The extractor emits these edges and the selector does not read them.

### Real commits

15 recent non-merge master commits with Python changes, replayed:

|                                    | value |
| ---------------------------------- | ----- |
| median selected test files, before | 429   |
| median selected test files, after  | 430   |
| test files added across all 15     | 1     |

This is the number that decides the recommendation.
The one addition was `products/access_control/backend/tests/test_access_control.py`, reached through a URL edge on an activity-log viewset.
The reason the gain is so small is not that the edges are wrong; it is that a typical commit already selects a few hundred to a few thousand test files through the same-app fallback, the API-client fallbacks, and Snob's own closure, so the tests a URL edge names are usually already in the set.

## Cost

Warm (a second run, `.pyc` cache populated), on this 4-core sandbox:

| Step                                                          | Seconds   |
| ------------------------------------------------------------- | --------- |
| `django.setup()`                                              | 2.5 - 3.8 |
| `signals` extractor (scan `sys.modules`, read receiver lists) | 6.4 - 6.7 |
| `models` extractor                                            | 0.13      |
| `urls`: force the URL conf and walk 4923 routes               | 8.4 - 8.9 |
| `urls`: parse 5233 test files, resolve 9383 URL literals      | 51 - 59   |
| **total**                                                     | **~76**   |

Notes for anyone costing this for real:

- The first run in a fresh container took **56 seconds just for the resolver walk**, against 8.9 warm. That is `.pyc` compilation of every view module, so a cold CI container pays it.
- The URL literal scan is the bulk of the cost and is the easy part to optimize: it resolves each literal against the full pattern list, and 6023 of the 9383 literals are strings that only look like paths and end at the catch-all.
- Without the `urls` extractor the whole thing is ~10 seconds.
- The artifact is ~200 KB of JSON.
- Invalidation is the unsolved part. The map is a function of the whole repository, so on a PR that changes routing it is stale exactly when it matters. Building it per PR (~76s once, in parallel with container setup) is affordable; caching it on master and reusing it on PRs is not obviously safe.
- `django.setup()` is not free of side conditions either. It needs `TEST=1`: under `DEBUG=1` the WSGI path in `PostHogConfig.ready()` resolves the self-capture team, which opens a database connection and fails where there is no database.

## What stays fundamentally ambiguous

- **Conditionally registered routes.** `/api/agentic/provisioning/resources/` resolves to the 404 handler in this configuration, so its tests get no edge. One `django.setup()` sees one configuration; multi-tenancy flags, EE modules and settings-gated routes change the answer.
- **Interpolated path segments.** The extractor substitutes placeholders for f-string interpolations, which works for ids and fails for a resource name (`f"/api/projects/{team}/{resource}/"`). 6023 literals end at the catch-all and are dropped rather than guessed.
- **Which file registered a router route.** Django records the mounting URLconf, not the `router.register(...)` call site, so a change to `posthog/api/rest_router.py` or a product's `routes.py` gets no route-level edge. Only `posthog/urls.py` does, as a 578-test hub.
- **Receivers connected lazily,** inside a request or a task rather than at `ready()`, are invisible to a setup-time snapshot.
- **Templates, admin, and dynamic dispatch.** The template engine can list its directories but not which view renders which template without parsing `render()` calls. `admin.site._registry` is exact but admin has few tests. Neither looked worth the cost.
- **Transitive framework edges.** Applying URL edges to the import closure of a diff instead of the diff itself degenerates immediately: the transitive importer closure of a typical 2-file commit is 12,946 production files, which pulls in every URL edge in the repository (599 test files). One hop out lands at 43-62 test files, two hops at 578. Only a real edge inside Snob's graph, traversed as part of its own closure, gets this right.

## Recommendation

**Land the URL extractor, keep it out of the selection path for now, and revisit it as part of narrowing the fallbacks rather than as a standalone win.**

Concretely:

1. The URL edges are the real finding: exact, deterministic, 93% new information, and they close a structural gap (a product's API tests living in `posthog/api/test/`) that no amount of token fuzzing will close. Worth keeping as a tool.
2. They are not worth wiring into CI on their own evidence. +1 test file over 15 replayed commits does not pay for ~76 seconds per PR plus a stale-artifact failure mode. And the single biggest win they produced, `posthog/urls.py` going from 2 selected test files to 578, is available for one line in `FULL_RUN_PATTERNS`, with no introspection at all. Take that line first.
3. What is not available any other way is the 564 precise edges across 58 view files, and those are the ones with nothing to add today, because the existing fallbacks already select hundreds to thousands of test files per diff. Precise edges add almost nothing on top of blunt fallbacks. What they can do is let the fallbacks shrink, and the signal numbers show the same effect from the other side (1184 to 227 for the median receiver file).
4. So the sequencing that makes this pay: pick one blunt fallback (`signal_handler_api_tests` is the biggest), validate a registry-derived replacement against the testmon coverage data from [#56370](https://github.com/PostHog/posthog/pull/56370), and ship the extractor as its input. Not the reverse.
5. Three findings are worth fixing on their own, independent of any of this: `posthog/urls.py` narrowing to two test files, `_django_app_for_path` returning a file path for files directly under `posthog/` or `ee/`, and `posthog/health.py` being middleware that the name rule does not recognize.
6. If Snob itself ever gains an API for injecting edges, revisit the whole thing. Most of what this prototype cannot do (second-hop helpers, `apps.py`, settings) is a consequence of injecting at the diff instead of inside the graph.

## Reproducing

```bash
# Build the edge map for this repository (~76s warm)
TEST=1 python tools/django_edges/extract.py --out /tmp/django_edges.json

# Cheap extractors only (~10s)
TEST=1 python tools/django_edges/extract.py --out /tmp/django_edges.json --extractors signals,models

# Before/after over view files, signal files and recent commits (~30 min; one Snob call per scenario)
uv run tools/django_edges/measure.py --edges /tmp/django_edges.json --out /tmp/measurements.json

# One PR's selection, with the edges
uv run tools/snob_backend_test_selection_shadow.py --base-ref origin/master --django-edges /tmp/django_edges.json --pretty

# The fixture reproduction
cd tools/django_edges/fixture && uv run demo.py --mutate
```
