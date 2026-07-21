---
title: Data catalog trust advisory on query responses - Plan
type: feat
date: 2026-07-21
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Data catalog trust advisory on query responses - Plan

## Goal Capsule

- **Objective:** When a HogQL query reads an uncertified warehouse table while the team's data catalog holds approved governed metrics, the query response carries a trust advisory — so an agent (or human) satisficing on a plausible raw table is corrected at the point of use, on the exact path it walked, through the highest-attention channel (the query result itself).
- **Authority hierarchy:** Repo conventions and mandatory skills override this plan on mechanics; the plan overrides ad-hoc judgment on scope.
- **Execution profile:** Django/HogQL backend plus the `ee/hogai` formatter layer. Zero changes to the MCP server (`services/mcp`) — its `execute-sql` tool forwards the backend-formatted string verbatim.
- **Stop conditions:** Stop and surface if the advisory cannot be built fail-soft (any path where it could break query execution), or if catalog lookups measurably slow the query hot path.

---

## Product Contract

### Summary

Attach a `data_catalog_trust` warning to `HogQLQueryResponse.warnings` when a query reads uncertified warehouse tables and approved metrics exist; render it into the agent-facing `execute-sql` result string via the existing warnings formatter.

### Problem Frame

An agent asked a business-metric question found a plausible uncertified warehouse table and answered from it, though an approved governed metric existed. Steering (a low-attention channel) was present and failed; the environment was silent on the path the agent actually took. Reviewer feedback also ruled out MCP-layer interception (the `exec search` surface is slated for removal). The durable, altitude-correct fix attaches the trust signal to the query response — it fires regardless of how the agent found the table and survives any MCP redesign.

### Requirements

- R1. A query resolving at least one warehouse (S3) table with no CERTIFIED certification (or a DEPRECATED one), for a team with the catalog flag on and at least one approved metric, gets a `data_catalog_trust` warning naming the flagged tables and up to ~5 approved metric names, pointing at `system.information_schema.metrics`.
- R2. The warning reaches agents with no MCP-server changes: it rides `HogQLQueryResponse.warnings` and the existing warning-prefix formatting of the `execute-sql` result string.
- R3. The advisory never breaks or degrades a query: builder is fail-soft (exception → no warning), gated on `is_data_catalog_enabled`, and respects catalog read access (fail closed like the information-schema surface).
- R4. Queries touching only certified tables, or no warehouse tables, or teams with no approved metrics or no flag, produce no warning — responses byte-identical to today.
- R5. Tenant-authored strings in the message are bounded: table names sanitized/capped; metric names are already identifier-safe by model constraint.

### Scope Boundaries

- Warehouse (S3) tables only in v1; saved-query views are a follow-up (certifications support them, resolution path differs).
- No frontend rendering of the new warning type (UI ignores unknown types).
- No query-to-metric relevance matching in the message.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **Point-of-use signal over discovery interception.** (session-settled: user-directed — chosen over keeping the MCP `exec search` integration: reviewer altitude objection plus first-principles analysis that the incident's cause was a silent environment at the point of use, not missing search results.)
- KTD2. **Copy the `build_access_control_warning` pattern verbatim** (`posthog/hogql/printer/access_control.py:16`): context accumulator → `build_*_warning` → appended to `warnings` in `HogQLQueryExecutor.execute()`. Warnings already survive response caching (`posthog/hogql_queries/query_runner.py` warnings merge).
- KTD3. **Extract used tables from the resolved query type** via `extract_base_table_types` (`posthog/hogql/resolver_utils.py`), the same mechanism `extract_warehouse_sources` uses — no resolver or context changes needed; the resolved `S3Table` carries the `table_id` certifications key on resource id, not name.
- KTD4. **Reach agents via the existing warnings formatter** (`ee/hogai/context/insight/format/__init__.py` `_format_warnings` + the prefix in `query_executor.py`) — backend tool layer, not the MCP server.

### Sequencing

Schema type → accumulator/resolver → builder + execute() wiring → formatter → tests → eval.

---

## Implementation Units

### U1. `DataCatalogTrustWarning` schema type

- **Files:** `frontend/src/queries/schema/schema-general.ts` (union alongside `AccessControlFilterWarning`), regenerated `posthog/schema.py`.
- **Approach:** `{ type: "data_catalog_trust", message, uncertified_tables: string[], approved_metrics: string[] }`; add to both union references. Regenerate via the schema build.

### U2. Used-table extraction

- **Files:** folded into `posthog/hogql/catalog_trust.py`.
- **Approach:** `_used_warehouse_tables(select_type)` over `extract_base_table_types` collects `(table_id, name)` for resolved `S3Table`s — including self-managed tables, which are certifiable. No resolver or context changes.

### U3. Builder + execute() wiring

- **Files:** `posthog/hogql/catalog_trust.py` (new), `posthog/hogql/query.py`.
- **Approach:** `build_data_catalog_trust_warning(context, team)`: gates (non-empty accumulator, `is_data_catalog_enabled`, catalog read access per the `_can_read_catalog` posture); certifications via the data-catalog facade filtered to used ids; approved metric names via `metrics_for_team(...).filter(status=APPROVED)` capped at 5; skip drift computation on the hot path; entire body fail-soft. Wire where `execute()` assembles `warnings`.
- **Test scenarios:** parameterized executor-level cases — uncertified+approved → warning with names; certified → none; deprecated cert → warning; no approved metrics → none; flag off → none; events-only query → none; builder exception → query still succeeds.

### U4. Formatter reach

- **Files:** `ee/hogai/context/insight/format/__init__.py`, `ee/hogai/context/insight/query_executor.py`.
- **Approach:** `format_data_catalog_trust_warnings` via the generic `_format_warnings(response, "data_catalog_trust", header)`; append to the existing warning prefix.
- **Test scenarios:** new type renders its block; absent type renders nothing.

### U5. Unprompted incident eval

- **Files:** `products/data_catalog/evals/` (case + seeder tweak).
- **Approach:** `governed_metric_vs_raw_table_unprompted` — the raw incident prompt with no official-definition nudge; the advisory in the decoy query result is what should rescue a satisficing agent. Ensure the decoy read path is scoreable (queryable decoy or failure-tolerant scorer).

---

## Verification Contract

| Gate                     | Command                                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------ |
| Backend tests            | `pytest` on new executor/formatter tests                                                   |
| MCP suite (shrinks back) | `hogli test services/mcp`                                                                  |
| Types                    | repo-wide `uv run mypy --cache-fine-grained .`                                             |
| Schema drift             | regen + `git diff` clean                                                                   |
| Pre-push                 | `hogli ci:preflight --fix`                                                                 |
| Point-of-use e2e         | eval transcript shows the advisory text inside the `execute-sql` result the agent received |

## Definition of Done

- Search interception fully removed; MCP suites green at master-parity plus retained steering/eval tests.
- Advisory ships with all R1–R5 verified by tests; eval runs locally with the advisory visible in the transcript.
- PR #72548 retitled/rewritten for the new approach; review thread answered.
