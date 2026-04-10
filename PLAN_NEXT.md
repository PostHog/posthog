# Error tracking isolation — remaining work

Supersedes the remaining-work sections of `PLAN.md` and the sequencing in
`products/error_tracking/MIGRATION_MATRIX.md`.
The high-level architecture goals are unchanged; this plan is strictly about
closing the gap between the current repo state and the definition of done.

## Implementation status

| Phase                                          | Status      | Notes                                                                                                                                                               |
| ---------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Phase 0 — Housekeeping                         | ✅ complete | All 5 items landed; facade tests fixed as a side benefit.                                                                                                           |
| Phase 1.5 — Tach layer flip                    | ✅ complete | Inverted layer order so `non_isolated` (periphery) depends on `products` (isolated core).                                                                           |
| Phase 7 — Delete `backend/api/`                | ✅ complete | Entire legacy shim package removed; no importers remained after Phase 0.                                                                                            |
| Phase 1 — Test factories                       | ✅ complete | `backend/test/factories.py` created; all 5 external tests migrated; `backend.models` removed from tach interfaces; new facade `count_issues_for_team` helper added. |
| Phase 2 — Infra extraction                     | ⏳ pending  | No longer tach-blocked; moves to straight refactor.                                                                                                                 |
| Phase 3 — Typed digest/remote-config contracts | ⏳ pending  | Unblocked.                                                                                                                                                          |
| Phase 4 — Facade read completeness             | ⏳ pending  | Unblocked.                                                                                                                                                          |
| Phase 5a — Typed query contracts               | ⏳ pending  | Blocked by Phase 4.                                                                                                                                                 |
| Phase 5b — Migrate query consumers             | ⏳ pending  | Blocked by Phase 5a.                                                                                                                                                |
| Phase 5c — Framework dispatch split            | ⏳ pending  | Blocked by Phase 5b.                                                                                                                                                |
| Phase 6 — Contract-check                       | ⏳ pending  | Blocked by Phase 3.                                                                                                                                                 |
| Phase 8 — Final tach lockdown                  | ⏳ pending  | Blocked by 1, 2, 5c, 6, 7.                                                                                                                                          |

### Side findings (not in original plan)

- **Phase 1.5 (new) — Tach layer flip** surfaced during Phase 0 tach
  verification and is now complete. See the Phase 1.5 section below.
- `backend/facade/enums.py` had zero external consumers and was removed
  outright rather than added to tach interfaces.
- Three facade tests in `backend/test/facade/test_facade_api.py` had
  pre-existing bugs (`summary.id == issue.id` comparing `str` to `UUID`,
  `self.create_team(...)` method not on `BaseTest`). Fixed as part of
  Phase 0 so the facade suite is now green.
- New facade helper `count_issues_for_team(team)` added during Phase 1
  so `test_personal_api_keys` could assert post-merge issue counts
  without importing the ORM model.

## Current gap, at a glance

| Area                                     | Status          | Blocker                                                                                        |
| ---------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------- |
| Business-consumer migration              | ~95%            | 5 external tests still import `backend.models`                                                 |
| Presentation separation                  | done            | —                                                                                              |
| Tach tightening                          | partial         | `backend.models`, `backend.sql`, `backend.embedding`, `backend.indexed_embedding` still public |
| Typed contracts (digest / remote-config) | missing         | digest helpers still return `dict`                                                             |
| Typed contracts (query results)          | missing         | facade re-exports runner classes instead of typed APIs                                         |
| Facade read completeness                 | partial         | no detail / preview / fingerprint-lookup / first-event APIs                                    |
| Contract-check                           | placeholder     | `compileall` is not contract-aware                                                             |
| Legacy `backend/api/` package            | dead code       | every module is a wildcard re-export shim                                                      |
| One internal test                        | broken boundary | `test_suppression_rule_filters.py` still imports `backend.api.utils`                           |

## Guiding principles

1. **Small, mergeable PRs.** Every phase below should be one PR, or a
   tight sequence of PRs when the phase is too large. No single PR should
   touch more than one external consumer group.
2. **Contracts before tach tightening.** Never remove a tach interface until
   the contract that replaces it is in place and at least one caller uses it.
3. **Don't break digest / remote-config output.** Both ship user-visible
   payloads. Introduce contracts as additive refactors, not semantic changes.
4. **Lazy imports inside facade are fine.** The goal is an external boundary,
   not a perfectly decoupled facade module.
5. **No speculative contracts.** Only add contract types that have an actual
   consumer in the same PR.

## Phase 0 — Housekeeping (single small PR)

Cheap, obvious fixes that unblock later phases without risk.

- Fix the internal legacy import in
  `products/error_tracking/backend/test/logic/test_suppression_rule_filters.py`
  to use `backend.rule_bytecode.generate_byte_code` instead of
  `backend.api.utils.generate_byte_code`.
- Collapse the `_team_id` `@overload` pair in `backend/facade/api.py:32-41`
  into a single two-line helper.
- Stop re-wrapping `TeamCountContract` into a dict in
  `get_issue_counts_by_team` and `get_symbol_set_counts_by_team`. Either
  return the contract directly (preferred) or drop the construction. Update
  `posthog/tasks/usage_report.py` if the return type changes.
- Decide the fate of `backend/facade/enums.py`:
  either add `products.error_tracking.backend.facade.enums` to the tach
  interface list, or fold the enums into `backend/facade/contracts.py` and
  delete `enums.py`. Whichever is picked, make sure the `__init__.py`
  re-exports match.
- Move `products/error_tracking/backend/facade/AUDIT.md` next to
  `MIGRATION_MATRIX.md` so migration docs live together, or delete it if
  this plan supersedes it.

Exit criteria: repo still green, no semantic changes, zero remaining
references to `backend.api.utils` from inside the product tests.

## Phase 1 — Sanctioned test factories (PR 1 from the old matrix)

Goal: no external test imports `backend.models`.

### Steps

1. Create `products/error_tracking/backend/test/factories.py`. Put it on
   the tach allowlist as an explicit test-only public interface:

   ```toml
   interfaces = [
       ...
       "products.error_tracking.backend.test.factories",
       ...
   ]
   ```

   The factories module should expose small builder helpers that return
   ORM instances, e.g.:

   ```python
   def create_issue(*, team, status="active", name=None, description=None) -> ErrorTrackingIssue
   def create_issue_fingerprint(*, team, issue, fingerprint, version=1) -> ErrorTrackingIssueFingerprintV2
   def create_issue_assignment(*, issue, user=None, role=None) -> ErrorTrackingIssueAssignment
   ```

   Helpers must accept / return the ORM type internally but be the only
   path non-product tests are allowed to touch models through.

2. Migrate each external caller to the factories and replace any ORM
   field assertions with facade reads where possible:
   - `posthog/test/test_permissions.py`
   - `posthog/api/test/test_personal_api_keys.py`
   - `posthog/tasks/test/test_usage_report.py`
   - `ee/hogai/context/error_tracking/test/test_context.py`
   - `posthog/hogql/database/schema/test/test_system_tables.py`

   Where a test still needs a raw ORM instance (e.g. for schema
   introspection in `test_system_tables.py`), do it through a factory
   return value, not a direct import.

3. Remove `products.error_tracking.backend.models` from the
   `products.error_tracking` tach interface list.

4. Run `tach check` locally to confirm there are no remaining leaks.

Exit criteria: `grep -rn "from products.error_tracking.backend.models"`
returns only results from inside `products/error_tracking/`.

## Phase 1.5 — Tach layer hierarchy fix ✅ complete

Side finding surfaced during Phase 0 verification.

Background: `products/signals/backend/management/commands/cleanup_signals.py`
and `products/tasks/backend/repository_readiness.py` import from
`products.error_tracking`, but `products.signals` and `products.tasks`
were declared as `non_isolated` layer while `products.error_tracking`
is now `products` layer. The original `tach.toml` had
`layers = ["products", "non_isolated"]`, which made `products` the
topmost layer and forbade `non_isolated` modules from importing it.

Fix: inverted the layer order to
`layers = ["non_isolated", "products"]`. This matches the standard
layered-architecture semantics where the isolated core sits _below_
the periphery, and the periphery freely depends on the core but not
vice versa. This is the mental model for a "public facade" — outer
modules consume inner modules through the facade.

Validation: `tach check` returned `All modules validated!` after the
flip with zero new violations anywhere in the repo.

No Python code changed.

## Phase 2 — Infra module extraction (PR 6 from the old matrix)

Goal: the remaining tach interfaces for `sql`, `embedding`, and
`indexed_embedding` are replaced by a single, intentional
`backend.infra` surface.

### Steps

1. Create `products/error_tracking/backend/infra/` with:
   - `schema.py` — everything currently exported from `backend/sql.py`
   - `embedding.py` — everything currently exported from
     `backend/embedding.py` and `backend/indexed_embedding.py` that is
     consumed cross-product (SQL constants, table metadata, MV names,
     `EMBEDDING_TABLES`, `KAFKA_DOCUMENT_EMBEDDINGS`, etc.)

   The originals can become re-export shims temporarily if the diff is
   too large in one PR — flag it in the commit message as a staged move.

2. Update tach:
   - Add `products.error_tracking.backend.infra` (or the two submodules)
     to the interface list.
   - Remove `backend.sql`, `backend.embedding`, `backend.indexed_embedding`.

3. Migrate external importers:
   - `posthog/conftest.py`
   - `posthog/clickhouse/schema.py`
   - `posthog/clickhouse/migrations/0083`, `0153`, `0155`, `0157`,
     `0174`, `0183`, `0191`, `0192`, `0226`
   - `posthog/hogql/database/schema/document_embeddings.py`
   - `posthog/api/embedding_worker.py`
   - `products/signals/backend/management/commands/cleanup_signals.py`

   ClickHouse migrations that are frozen (already merged) can keep
   importing the re-export shim; new migrations must use `backend.infra`.

4. Once the shims are unused from outside, delete the re-export files
   inside `backend/` and remove the old interface entries from tach.

Exit criteria: `backend.sql`, `backend.embedding`, `backend.indexed_embedding`
are no longer listed as tach interfaces; no external file imports them.

## Phase 3 — Typed digest + remote-config contracts

Goal: the facade stops leaking untyped `dict` / `list[dict]` payloads for
payloads that are already in production.

### New contracts (in `backend/facade/contracts.py`)

```python
@dataclass(frozen=True)
class WeekOverWeekChangeContract:
    value: float
    direction: Literal["up", "down", "flat"]
    higher_is_better: bool

@dataclass(frozen=True)
class ExceptionSummaryContract:
    exception_count: int
    ingestion_failure_count: int
    prev_exception_count: int | None

@dataclass(frozen=True)
class CrashFreeSessionsContract:
    total_sessions: int
    crash_free_rate: float
    crash_free_rate_change: WeekOverWeekChangeContract | None
    total_sessions_change: WeekOverWeekChangeContract | None

@dataclass(frozen=True)
class SparklineBarContract:
    height_percent: float

@dataclass(frozen=True)
class DailyExceptionCountContract:
    day: date
    count: int
    height_percent: float

@dataclass(frozen=True)
class DigestIssueCardContract:
    id: str
    name: str | None
    description: str | None
    occurrence_count: int
    sparkline: list[SparklineBarContract]
    url: str

@dataclass(frozen=True)
class ClientSafeSuppressionRuleContract:
    id: str
    bytecode: list  # kept as list for JSON-round-trip compatibility

@dataclass(frozen=True)
class RemoteConfigContract:
    autocapture_exceptions: bool
    suppression_rules: list[ClientSafeSuppressionRuleContract]
```

### Facade surface changes

- Refactor `get_crash_free_sessions`, `get_daily_exception_counts`,
  `get_exception_summary_for_team`, `get_new_issues_for_team`,
  `get_top_issues_for_team`, `compute_week_over_week_change` to return
  the contracts above.
- Update `ErrorTrackingWeeklyDigestProjectContract` fields to use the
  new typed contracts instead of `dict` / `list[dict]`.
- Refactor `build_remote_config(team)` to return `RemoteConfigContract`.
  Keep a thin JSON-serializer helper on the facade for
  `posthog/models/remote_config.py` so the wire shape does not change.

### Consumer updates (same PR or follow-up per consumer)

- `posthog/tasks/email.py` (weekly digest template data) — swap dict
  access for contract fields; keep template context keys stable.
- `posthog/models/remote_config.py` — call a new
  `build_remote_config_payload(team) -> dict` on the facade so the
  Django HyperCache JSON contract is byte-stable.
- Update `backend/test/test_weekly_digest.py` assertions.
- Add targeted contract tests under `backend/test/facade/`.

Exit criteria: no public facade function returns `dict` or `list[dict]`
for digest or remote-config data. The over-the-wire JSON for
`/decide` / remote-config endpoints is byte-identical to before
(verify with a snapshot test in `posthog/test/test_remote_config.py`).

## Phase 4 — Facade read completeness

Goal: replace the two remaining pieces of "reach into the runner" logic
that force us to keep the runner classes on the facade.

### New contracts

```python
@dataclass(frozen=True)
class ErrorTrackingIssuePreviewContract:
    id: str
    name: str | None
    description: str | None
    status: str
    first_seen: datetime | None
    last_seen: datetime | None
    library: str | None
    assignee: ErrorTrackingIssueAssignmentContract | None

@dataclass(frozen=True)
class ErrorTrackingIssueDetailContract(ErrorTrackingIssuePreviewContract):
    external_issues: list[dict]  # TODO: type once external refs facade exists
    cohort: str | None
    first_event: dict | None
```

### New facade APIs

- `get_issue_detail(team, issue_id) -> ErrorTrackingIssueDetailContract | None`
- `get_issue_by_fingerprint(team, fingerprint) -> ErrorTrackingIssueContract | None`
- `get_issue_first_event(team, issue_id) -> dict | None`
  (typed as `dict` for now; promote to a `ClickhouseEventContract` only
  if a second consumer appears)

### Consumer updates

- `ee/hogai/context/error_tracking/context.py` — stop building
  `ErrorTrackingQuery` manually; use `get_issue_first_event` instead.
- `presentation/issues.py:retrieve` — route the fingerprint-redirect
  path through `get_issue_by_fingerprint`.

Exit criteria: `ee/hogai/context/error_tracking/context.py` no longer
imports `posthog.hogql_queries.query_runner` or any Error tracking
internal module.

## Phase 5 — Query facade and framework adapter split

This is the largest phase. It should be split into 2–3 PRs.

### 5a — Add typed query entry points (PR A)

New contracts:

```python
@dataclass(frozen=True)
class ErrorTrackingIssueAggregationContract:
    occurrences: int
    users: int
    sessions: int
    volume_buckets: list[int] | None

@dataclass(frozen=True)
class ErrorTrackingEventSummaryContract:
    uuid: str
    timestamp: datetime
    properties: dict

@dataclass(frozen=True)
class ErrorTrackingQueryResultRowContract:
    issue: ErrorTrackingIssuePreviewContract
    aggregations: ErrorTrackingIssueAggregationContract
    first_event: ErrorTrackingEventSummaryContract | None
    last_event: ErrorTrackingEventSummaryContract | None

@dataclass(frozen=True)
class ErrorTrackingQueryResultContract:
    rows: list[ErrorTrackingQueryResultRowContract]
    has_more: bool

@dataclass(frozen=True)
class ErrorTrackingIssueCorrelationResultContract: ...
@dataclass(frozen=True)
class ErrorTrackingSimilarIssueContract: ...
@dataclass(frozen=True)
class ErrorTrackingBreakdownsQueryResultContract: ...
```

New facade APIs:

- `query_issues(team, query: ErrorTrackingQuery) -> ErrorTrackingQueryResultContract`
- `query_issue_correlations(team, query) -> ErrorTrackingIssueCorrelationResultContract`
- `query_similar_issues(team, query) -> list[ErrorTrackingSimilarIssueContract]`
- `query_issue_breakdowns(team, query) -> ErrorTrackingBreakdownsQueryResultContract`

Implementation: thin wrappers that instantiate the existing runners
internally and map their responses to contracts. No semantic changes.

### 5b — Migrate external consumers (PR B)

- `products/signals/backend/temporal/backfill_error_tracking.py` — call
  `query_issues` instead of the generic `get_query_runner` dance.
- `products/posthog_ai/scripts/hogql_example/__init__.py` — same.
- `products/error_tracking/backend/tools/search_issues.py` — call
  `query_issues` rather than assembling a runner directly; drop the
  duplicated dashboard defaults in favor of a shared
  `default_issue_query(...)` helper in the facade.

### 5c — Framework dispatch adapter (PR C)

- In `posthog/hogql_queries/query_runner.py`, replace the current
  lazy imports of concrete runner classes with calls into a new
  `backend/presentation/query_dispatch.py` (or `backend/facade/query_dispatch.py`)
  module that returns the runner object for a given `ErrorTrackingQuery`
  subtype.
- Stop re-exporting `ErrorTrackingQueryRunner`,
  `ErrorTrackingIssueCorrelationQueryRunner`,
  `ErrorTrackingSimilarIssuesQueryRunner`, and
  `ErrorTrackingBreakdownsQueryRunner` from `backend/facade/__init__.py`.
- Classify the dispatch module explicitly in tach as a framework
  interface (comment-labeled "framework dispatch — not a product API").

Exit criteria:

- No external file imports
  `products.error_tracking.backend.hogql_queries.*` directly.
- `backend/facade/__init__.py:__all__` no longer lists runner classes.
- `tach.toml` has no `backend.hogql_queries.*` interfaces.

## Phase 6 — Meaningful contract-check

Goal: `backend:contract-check` fails CI if the public surface drifts.

### Approach

1. Add a small script at
   `products/error_tracking/backend/facade/_contract_check.py` that:
   - Imports `products.error_tracking.backend.facade` dynamically.
   - Walks `__all__` and every dataclass in `contracts.py`.
   - Serializes each to a deterministic snapshot: for functions, the
     signature (name, parameter kinds/types, return type string); for
     contracts, the frozen-ness, field names, and field types.
   - Compares against a committed lock file at
     `products/error_tracking/backend/facade/.contract-lock.json`.
   - Exits non-zero on removals, type narrowings, or parameter drops.
     New additions are allowed and update the lock file with a
     `--update` flag.
2. Wire `package.json`:

   ```json
   "backend:contract-check": "python products/error_tracking/backend/facade/_contract_check.py"
   ```

3. Add a lint-staged hook that runs the check when anything under
   `backend/facade/` changes.
4. Document the workflow in `backend/facade/CONTRACT_CHECK.md`: how to
   intentionally bump the lock after a reviewed breaking change.

Exit criteria: deleting a field from `ErrorTrackingIssueContract` makes
`backend:contract-check` fail locally and in CI.

## Phase 7 — Delete the legacy `backend/api/` package

Goal: `backend/api/` stops existing.

### Steps

1. After Phase 0 moves `test_suppression_rule_filters.py` off
   `backend.api.utils`, verify nothing else imports from
   `products.error_tracking.backend.api.*`:

   ```bash
   rg "from products\.error_tracking\.backend\.api" --type py
   ```

2. Delete every `backend/api/*.py` file. They are all wildcard
   re-export shims today, so this is a pure deletion.
3. Delete `backend/api/test/` if any stragglers remain (the directory
   was already removed; `api/__init__.py` / subfiles are the last
   holdouts).
4. Remove `backend.api` from tach if it was ever listed.

Exit criteria: `products/error_tracking/backend/api/` does not exist.

## Phase 8 — Final tach lockdown

Once all the phases above are merged, the desired tach interface list
for `products.error_tracking` should read:

```toml
interfaces = [
    # Business facade (stable cross-product surface).
    "products.error_tracking.backend.facade",
    # Public HTTP wiring.
    "products.error_tracking.backend.presentation.views",
    # Infra / framework surfaces — intentionally not the facade.
    "products.error_tracking.backend.apps",
    "products.error_tracking.backend.infra",
    "products.error_tracking.dags",
    # Test-only sanctioned helper.
    "products.error_tracking.backend.test.factories",
]
```

Anything else — `models`, `sql`, `embedding`, `indexed_embedding`,
`weekly_digest`, `remote_config`, `tools.*`, `hogql_queries.*`, `logic`,
`rule_bytecode` — must not appear in the list. Any regression should be
caught by `tach check` in CI.

## Recommended PR sequence

The phases are partially independent. Recommended merge order:

1. Phase 0 — housekeeping
2. Phase 1 — test factories (unlocks removing `backend.models` from tach)
3. Phase 2 — infra extraction (unlocks removing the infra interfaces)
4. Phase 3 — typed digest + remote-config contracts
5. Phase 4 — facade read completeness
6. Phase 5a → 5b → 5c — query facade and framework adapter
7. Phase 6 — meaningful contract-check
8. Phase 7 — delete `backend/api/`
9. Phase 8 — final tach lockdown (may be folded into Phase 5c)

Phases 1–4 can proceed in parallel once Phase 0 lands. Phase 5 depends
on Phase 4. Phases 6–8 are cleanup and should land last.

## Definition of done (recheck)

Carried over from `PLAN.md` and re-validated against this plan:

- ✅ External business consumers import only
  `products.error_tracking.backend.facade` — **after Phase 1**
- ✅ Public HTTP wiring imports only
  `products.error_tracking.backend.presentation.views` — **done**
- ✅ Stable cross-product data uses contract types — **after Phase 3 + 5a**
- ✅ `backend.models`, `weekly_digest`, `remote_config`, and search/query
  internals are no longer accidental public APIs — **after Phase 5c**
- ✅ Tach exposes only the intentionally public interfaces — **after Phase 8**
- ✅ `backend:contract-check` is meaningful — **after Phase 6**
- ✅ Implementation-only changes inside Error tracking avoid unnecessary
  downstream retesting — **falls out of Phases 1–5 combined**

## Risks and escape hatches

- **Phase 3 is user-visible.** Remote config and digest email changes
  must be covered by a wire-format snapshot test before any refactor
  lands. If the snapshot drifts, revert and retry.
- **Phase 5c may surface hidden runner coupling.** Query dispatch is
  also used by the frontend insights path. Before removing the class
  re-exports, search for string-based references
  (`ErrorTrackingQueryRunner` name, `query_runner.ErrorTracking...`
  entries in registries, `isinstance` checks in tests) — not just
  imports.
- **Tach updates are risky to stack.** Land one tach change per PR so
  individual reverts stay surgical.
- **Factories are a one-way door.** Once external tests stop importing
  models, keep the factories intentionally narrow so they do not grow
  into a second public surface.

## Out of scope

- Rewriting `backend/hogql_queries/*` internals beyond what is needed
  for contract mapping.
- Any frontend-side changes.
- Moving `backend/weekly_digest.py` or `backend/logic.py` into deeper
  subdirectories — Phase 8 tightens tach against them without renaming.
- Adding Max tool or MCP surface beyond what exists today. The facade
  query APIs added in Phase 5a are enough to unblock future tool work.
