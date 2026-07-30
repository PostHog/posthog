# Datasets foundation

> **Living implementation tracker. Update the checklist, decisions, and progress log as work lands.**
> This file is the source of truth when the implementation spans context compactions.

Status: foundation complete; sync current `master` and refresh generated contracts before publishing
Branch: `feat/aio-datasets-foundation`
Last updated: 2026-07-30

## Objective

Ship a small, durable datasets foundation before enabling `llm-analytics-datasets` for users.

The first usable workflow is:

1. Save the input and actual output from a live trace or generation.
2. Add or edit the expected output.
3. Keep every item edit as immutable history.
4. Read or export the dataset at an exact revision for offline evaluation elsewhere.

Experiments can consume this foundation later. They are not required to use a dataset.

## Working principles

- Prefer the smallest model that preserves future compatibility.
- Keep one mutation path for UI, REST, MCP, and future imports.
- Put invariants in domain logic inside narrow transactions, not in individual clients.
- Follow existing AI observability names and API conventions.
- Use generated OpenAPI types. Do not add parallel handwritten API contracts.
- Add useful field and operation descriptions where Django, DRF, OpenAPI, or MCP supports them.
- Comment only where an invariant or non-obvious tradeoff is not clear from the code.
- Do not build compatibility layers for the current dataset rows. The feature is at 0% and existing data can be discarded.
- Do not add input or output schemas yet. The version model leaves room to add them later.

## Scope

The foundation change covers:

- the dataset, dataset revision, item, and item version models;
- the mutation logic and its invariants;
- REST and generated OpenAPI contracts;
- MCP tools backed by those REST operations;
- server-side rollout gating;
- focused backend, API, permission, and MCP contract tests;
- the minimum frontend adjustments needed to compile against the breaking API.

The foundation also includes the minimum product workflow for editing expected output separately, preserving captured source output and provenance, and archiving or restoring items.

The follow-up product workflow covers:

- item history and dataset revision views;
- download/export UI;
- deep-link, loading, and permission-state fixes.

## Locked design decisions

### Dataset contents

- `input` is required and can contain any non-null JSON value.
- `expected_output` is optional and can contain any non-null JSON value. JSON `null` means absent.
- `source_output` is optional and stores the actual output captured from production. JSON `null` means not captured.
- `metadata` is always a JSON object.
- Saving from a trace fills `input`, `source_output`, and provenance. It does not guess `expected_output`.
- `source_trace_id`, `source_event_id`, and `source_timestamp` are copied provenance, not foreign keys. Trace data is event-backed and may expire independently of the dataset.

### Versioning

- `DatasetItem` is the stable identity.
- `DatasetItemVersion` rows are immutable snapshots.
- Every item create, content-changing update, archive, or restore creates one `DatasetRevision`.
- An update whose content is unchanged returns the current version without creating history.
- A batch mutation will share one dataset revision when batch APIs are added.
- `Dataset.current_revision` points at the latest committed dataset revision.
- `DatasetItem.current_version` points at the latest item version.
- Updates never rewrite an old version.
- Restore creates a new version by copying a selected historical version.
- Archive creates a new version with `archived=true`; it does not delete history.
- Mutations require the caller's `base_version`. A stale base version returns `409 Conflict`.
- `external_id` is the optional caller-owned stable key. It is unique within a dataset and is the first idempotent-create mechanism.
- Repeating a create with the same case-sensitive `external_id` and equivalent content returns the existing item without creating a revision. Different content returns `409 Conflict`.
- Generic idempotency keys are deferred until batch import or another concrete retry workflow needs them.

### Lifecycle

- Datasets are archived, not hard-deleted.
- Dataset items are archived through their current version, not hard-deleted.
- An archived dataset remains readable but rejects item mutations.
- Restoring a dataset does not change its items.
- An item's dataset membership and `external_id` are immutable after creation.
- Captured source output and provenance are immutable after creation. They record where the item originated, while later versions may edit the working input.

### Schemas

- There are no `input_schema` or `output_schema` fields in this foundation.
- JSON values remain flexible while usage patterns are still being learned.
- If schemas are added later, they should be versioned with dataset revisions rather than mutating the meaning of historical items.
- Dataset metadata is descriptive and live. An exact dataset revision describes item membership and item content, not historical dataset name, description, or metadata.

## Data model

All four models are team-scoped and use `TeamScopedRootMixin`. Every row has `team_id`, even when it can be reached through another row.

### `Dataset`

| Field                  | Shape           | Notes                                                                          |
| ---------------------- | --------------- | ------------------------------------------------------------------------------ |
| `id`                   | UUID            | Stable dataset ID                                                              |
| `team`                 | FK              | Tenant boundary                                                                |
| `name`                 | string          | Trimmed; unique within a team                                                  |
| `description`          | string          | Empty string when absent                                                       |
| `metadata`             | JSON object     | Empty object when absent                                                       |
| `archived`             | boolean         | No hard-delete API                                                             |
| `current_revision`     | nullable FK     | Latest committed `DatasetRevision`; API revision is null before the first item |
| creation/update fields | existing mixins | Includes creator and timestamps                                                |

### `DatasetRevision`

| Field           | Shape            | Notes                                   |
| --------------- | ---------------- | --------------------------------------- |
| `id`            | UUID             | Stable revision ID                      |
| `team`          | FK               | Tenant boundary                         |
| `dataset`       | FK               | Owning dataset                          |
| `revision`      | positive integer | Unique and monotonic within the dataset |
| creation fields | existing mixin   | Creator and commit timestamp            |

Keep this row deliberately small. The related item versions explain what changed.

### `DatasetItem`

| Field                  | Shape           | Notes                                                                           |
| ---------------------- | --------------- | ------------------------------------------------------------------------------- |
| `id`                   | UUID            | Stable item ID                                                                  |
| `team`                 | FK              | Tenant boundary                                                                 |
| `dataset`              | FK              | Immutable owner                                                                 |
| `external_id`          | nullable string | Optional opaque, case-sensitive caller key; unique within the dataset           |
| `current_version`      | nullable FK     | Latest immutable version; temporarily null only inside the creation transaction |
| creation/update fields | existing mixins | Creator and timestamps                                                          |

### `DatasetItemVersion`

| Field              | Shape              | Notes                                                  |
| ------------------ | ------------------ | ------------------------------------------------------ |
| `id`               | UUID               | Stable version-row ID                                  |
| `team`             | FK                 | Tenant boundary                                        |
| `dataset_item`     | FK                 | Stable item identity                                   |
| `dataset_revision` | FK                 | Dataset snapshot that introduced this version          |
| `version`          | positive integer   | Unique and monotonic within the item                   |
| `archived`         | boolean            | Current visibility comes from the pointed-to version   |
| `input`            | JSON               | Required and non-null                                  |
| `expected_output`  | nullable JSON      | User-authored target; JSON `null` means absent         |
| `source_output`    | nullable JSON      | Actual captured output; JSON `null` means not captured |
| `metadata`         | JSON object        | Empty object when absent                               |
| `source_trace_id`  | nullable string    | Source trace deep-link key                             |
| `source_event_id`  | nullable string    | Generation or other event within the trace             |
| `source_timestamp` | nullable timestamp | Needed to retrieve event-backed trace data             |
| creation fields    | existing mixin     | Creator and immutable commit timestamp                 |

### Database constraints and indexes

- Unique `(team, name)` on datasets.
- Unique `(dataset, revision)` on dataset revisions.
- Unique `(dataset_item, version)` on item versions.
- Unique `(dataset_item, dataset_revision)` on item versions.
- Conditional unique `(dataset, external_id)` when `external_id` is not null.
- Current-item list index beginning with `(team, dataset)`.
- Revision-history index on `(dataset, -revision)`.
- Item-history index on `(dataset_item, -version)`.
- Provenance indexes are added only when a real lookup path uses them.

## Invariants

The mutation layer must enforce these rules inside `transaction.atomic()` while holding the parent dataset row lock:

1. Every related row has the same `team_id`.
2. The requested dataset belongs to the URL team and passes dataset object-level access control.
3. An archived dataset accepts no item mutation.
4. An item's dataset and external ID never change.
5. Every item version's item and dataset revision belong to the same dataset and team.
6. Dataset revisions increase by exactly one.
7. Item versions increase by exactly one.
8. `Dataset.current_revision` points to a revision from that dataset.
9. `DatasetItem.current_version` points to a version from that item.
10. A supplied `base_version` must equal the current item version.
11. Source output and provenance cannot be changed after item creation.
12. `source_event_id` requires `source_trace_id` and `source_timestamp`.
13. `source_trace_id` requires `source_timestamp`; a timestamp without a trace ID is rejected.
14. Metadata is an object. Input and present outputs cannot be JSON `null`.
15. API payload sizes and list page sizes are bounded.
16. No API, MCP tool, or UI path writes version tables directly.

Database constraints cover local uniqueness, JSON shape, and provenance combinations. Cross-row ownership rules stay in the mutation layer because representing composite foreign keys in Django would add a second, non-standard relation system for four internal models.

## Mutation interface

Keep the internal interface function-based and small unless implementation pressure proves a class is clearer:

- `create_dataset(...)`
- `update_dataset(...)`
- `archive_dataset(...)`
- `restore_dataset(...)`
- `create_dataset_item(...)`
- `update_dataset_item(...)`
- `archive_dataset_item(...)`
- `restore_dataset_item(...)`

Each item mutation returns the stable item, its effective version, and whether it created a version. Reads do not go through this module.

Do not put event capture or other irreversible side effects inside the transaction. Emit them after commit.

Item PATCH uses field-level merge semantics:

- omitted editable fields are copied from the current version;
- `expected_output: null` clears the expected output;
- `input: null` and `metadata: null` are invalid;
- `{}` clears metadata;
- source output and provenance are not accepted by the update serializer.

## REST and OpenAPI contract

Retain the existing top-level PostHog resource names to avoid needless routing machinery:

### Datasets

- `GET /api/projects/{project_id}/datasets/`
- `POST /api/projects/{project_id}/datasets/`
- `GET /api/projects/{project_id}/datasets/{dataset_id}/`
- `PATCH /api/projects/{project_id}/datasets/{dataset_id}/`
- `POST /api/projects/{project_id}/datasets/{dataset_id}/archive/`
- `POST /api/projects/{project_id}/datasets/{dataset_id}/restore/`
- `GET /api/projects/{project_id}/datasets/{dataset_id}/revisions/`

### Dataset items

- `GET /api/projects/{project_id}/dataset_items/?dataset={dataset_id}`
- `POST /api/projects/{project_id}/dataset_items/`
- `GET /api/projects/{project_id}/dataset_items/{item_id}/`
- `PATCH /api/projects/{project_id}/dataset_items/{item_id}/`
- `POST /api/projects/{project_id}/dataset_items/{item_id}/archive/`
- `POST /api/projects/{project_id}/dataset_items/{item_id}/restore/`
- `GET /api/projects/{project_id}/dataset_items/{item_id}/versions/`

Contract rules:

- No `DELETE` or `PUT`.
- Dataset item list requires `dataset`.
- Item create accepts `dataset`, optional `external_id`, and version content.
- Item update accepts changed version content plus required `base_version`.
- Archive accepts required `base_version`.
- Restore accepts required `base_version` and optional `source_version`.
- Current item responses expose stable item fields plus flattened current-version content, `version`, `version_id`, and `dataset_revision`.
- Version and revision list responses are paginated.
- Item list accepts `?revision=N`. It selects each item's latest version whose dataset revision is at or before `N`, then excludes versions archived at that point.
- List endpoints default to 50 results and accept at most 100 per page.
- Separate read and write serializers define precise generated types.
- Every serializer field and custom action has concise `help_text` or schema descriptions.
- Conflict responses are typed and return the current version where useful.

## Permissions and rollout gate

- Keep the established `dataset:read` and `dataset:write` personal API scopes.
- Apply `AccessControlPermission` to datasets.
- Resolve item access through its exact parent dataset so item endpoints cannot bypass or combine object-level grants from another dataset.
- Apply `PostHogFeatureFlagPermission` with `posthog_feature_flag = "llm-analytics-datasets"` to both viewsets.
- Gate frontend routes and MCP tools on the same feature flag.
- Test session auth, personal API keys, object-level denial, cross-team IDs, archived parents, and the disabled flag.

## MCP and HogQL

Enable only atomic tools backed by the REST contract:

- `llma-dataset-list`
- `llma-dataset-get`
- `llma-dataset-create`
- `llma-dataset-update`
- `llma-dataset-archive`
- `llma-dataset-restore`
- `llma-dataset-revision-list`
- `llma-dataset-item-list`
- `llma-dataset-item-get`
- `llma-dataset-item-create`
- `llma-dataset-item-update`
- `llma-dataset-item-archive`
- `llma-dataset-item-restore`
- `llma-dataset-item-version-list`

Tool requirements:

- Read tools use `dataset:read`; mutation tools use `dataset:write`.
- Titles and descriptions state whether a tool creates a new immutable version.
- Annotations accurately describe read-only, destructive, and idempotent behavior.
- There is no delete tool.
- Update, archive, and restore expose `base_version`.
- Tools remain unavailable when the dataset feature flag is disabled.

Defer `system.datasets`, `system.dataset_items`, and `system.dataset_item_versions` while the feature flag is at 0%. The generic HogQL query surface cannot enforce this product feature flag, so adding the tables now would bypass the rollout gate. Add them once query access can use an equivalent gate or the flag is removed. The REST mutation path remains authoritative.

## Migration and cutover

- Do not backfill, dual-write, or preserve current dataset rows.
- Create the new active tables in one foundation migration.
- Keep the old physical tables during the rolling deploy so old application instances do not fail while the migration is live.
- Point the new model state at the new tables with `SeparateDatabaseAndState`.
- Remove the legacy tables' foreign keys to the hot Team and User tables while leaving their columns and data in place.
- Drop the unused legacy tables only in a later cleanup after every instance runs the new code. That cleanup does not block rollout.
- Treat the `_v2` names as permanent. Renaming internal tables later has no product value.
- Before deployment, confirm that the legacy tables have no rows that need preserving and no non-REST writer is active. The user has explicitly accepted discarding current rows, but the existing REST API was not server-gated.
- The rolling-deploy window may strand a write made by an old instance in a legacy table. This is accepted only while the feature remains at 0% and the pre-deploy audit confirms there are no active writers. If that assumption is false, ship a write freeze first.
- Update or disable the existing Dagster evaluator in the same cutover because item JSON values are no longer restricted to objects.
- Run the Django migration safety checks and the IDOR model-coverage check before merging.

The active backing-table names retain the `llm_analytics_` prefix and a permanent `_v2` suffix for the one-deploy cutover.

## Implementation checklist

### 1. Durable plan and contract

- [x] Record the scope, model, invariants, API, and rollout decisions here.
- [x] Re-check the plan after the first model/API pass and record any changed decision.

### 2. Data model and mutation layer

- [x] Replace the active `Dataset` and `DatasetItem` model definitions.
- [x] Add `DatasetRevision` and `DatasetItemVersion`.
- [x] Add fail-closed team-scoped managers to all four models.
- [x] Add constraints and only the indexes justified by current reads.
- [x] Add the no-backfill cutover migration.
- [x] Implement the single mutation module with row locks and optimistic concurrency.
- [x] Verify archive, restore, provenance, and parent/team invariants.

### 3. REST and generated contracts

- [x] Replace the current serializers with explicit read/write serializers.
- [x] Remove hard delete and full update operations.
- [x] Add archive, restore, revision, and version actions.
- [x] Require the dataset filter for item lists.
- [x] Implement exact-revision item lists.
- [x] Enforce parent dataset access for every item operation.
- [x] Add the server-side feature flag permission.
- [x] Add field and operation descriptions.
- [x] Regenerate OpenAPI and frontend types.
- [x] Make the minimum frontend changes needed for type safety.

### 4. MCP and query access

- [x] Replace disabled legacy dataset tool entries with the atomic tool set.
- [x] Add correct scopes, feature-flag gates, descriptions, and annotations.
- [x] Generate and inspect MCP schemas.
- [x] Defer system tables until they can honor the feature gate.

### 5. Validation

- [x] Model tests cover immutable history and constraints.
- [x] Mutation tests cover stale writes, monotonic revisions, archive/restore, provenance, and cross-team rejection.
- [x] API tests cover schemas, pagination, permissions, feature gating, and conflict responses.
- [x] Personal API key tests cover custom action scope lists.
- [x] MCP generated-schema validation covers tool availability and required inputs.
- [x] Run focused backend tests.
- [x] Run migration checks and IDOR coverage.
- [x] Run OpenAPI generation and generated-file checks.
- [x] Run focused frontend typecheck and dataset tests.
- [x] Run the full repository mypy check.
- [x] Run `hogli ci:preflight --fix`.

### 6. Product workflow follow-up

- [x] Separate expected output from captured source output in the editor.
- [x] Preserve source provenance when saving from a trace or generation.
- [x] Add item archive and restore controls.
- [ ] Add item history and historical-version restore UI.
- [ ] Add dataset revision selection and JSONL download/export.
- [ ] Fix item deep links independently of the current page.
- [ ] Align viewer controls and loading/error states with backend permissions.
- [x] Add focused frontend coverage for the implemented workflows.
- [ ] Add end-to-end coverage for the history and export workflow.

## Explicit non-goals

- Dataset experiments, runs, scorers, or result tables.
- Input/output JSON Schema.
- Prompt or model configuration on datasets.
- Bulk import and bulk editing.
- Named snapshots or branches.
- Dataset-to-dataset joins or derived datasets.
- Hard deletion.
- Compatibility aliases for the old `output`, `ref_trace_id`, `ref_source_id`, or `deleted` fields.
- A generic repository or event-sourcing framework.

## Decisions

| Date       | Decision                                                                                     | Reason                                                                                                                              |
| ---------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| 2026-07-30 | Version stable items with immutable item-version rows.                                       | Historical exports and future experiments must not change when an item is edited.                                                   |
| 2026-07-30 | Add an explicit dataset revision for every item mutation.                                    | A dataset needs an exact, reproducible snapshot identity independent of timestamps.                                                 |
| 2026-07-30 | Store `expected_output` and `source_output` separately.                                      | A captured production response is evidence, not automatically the desired answer.                                                   |
| 2026-07-30 | Keep `source_trace_id`, plus `source_event_id` and `source_timestamp`, as copied provenance. | Datasets outlive event retention and must not depend on a hard trace foreign key.                                                   |
| 2026-07-30 | Defer input/output schemas.                                                                  | Flexible JSON is sufficient now, and schema semantics can be added at the revision level later.                                     |
| 2026-07-30 | Use flat dataset and dataset-item resources.                                                 | This follows existing PostHog routing and keeps the API/codegen surface simple; parent checks still live server-side.               |
| 2026-07-30 | Replace current data without backfill or compatibility aliases.                              | The rollout is at 0% and current rows are explicitly disposable.                                                                    |
| 2026-07-30 | Keep old physical tables only for rolling-deploy safety.                                     | This avoids dual-write logic while preventing old instances from querying removed tables during deploy.                             |
| 2026-07-30 | Defer generic idempotency keys.                                                              | `external_id`, uniqueness, and optimistic concurrency address the current workflows without premature request-ledger machinery.     |
| 2026-07-30 | Treat JSON `null` as an absent optional output.                                              | PostgreSQL and Django do not preserve a useful absent-versus-JSON-null distinction without extra presence columns.                  |
| 2026-07-30 | Dataset revisions cover item state only.                                                     | Dataset metadata is descriptive today; future behavioral config belongs on revisions when introduced.                               |
| 2026-07-30 | Keep cross-row ownership checks in the mutation layer.                                       | Local database constraints remain valuable, but custom composite relations would add disproportionate ORM and migration complexity. |
| 2026-07-30 | Make source output and provenance immutable after creation.                                  | They describe captured evidence and should not drift independently of their source IDs.                                             |
| 2026-07-30 | Keep `_v2` as the permanent physical table suffix.                                           | Renaming internal tables later adds migration risk without user value.                                                              |
| 2026-07-30 | Defer HogQL system tables while the rollout flag is disabled.                                | The generic query surface cannot currently enforce the dataset feature flag.                                                        |
| 2026-07-30 | Accept the rolling-deploy legacy-write window only after a no-writer audit.                  | The feature is at 0% and current data is explicitly disposable; if that assumption changes, a write freeze becomes required.        |
| 2026-07-30 | Do not create a revision for an unchanged item update.                                       | A retry or redundant save should not manufacture history or advance a reproducible dataset snapshot.                                |
| 2026-07-30 | Cap REST list pages at 100 results, with a default of 50.                                    | Bounded responses protect REST and MCP callers without adding a second pagination mechanism.                                        |
| 2026-07-30 | Authorize item operations against their exact parent dataset.                                | A grant on one dataset must never satisfy access checks for an item in another dataset.                                             |

## Progress log

| Date       | Update                                                                                                                                                                                                                                                                                                                        |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-07-30 | Created the durable plan on a fresh branch from current `master`. No implementation changes yet.                                                                                                                                                                                                                              |
| 2026-07-30 | Added the four-model schema, immutable mutation service, and a state-only cutover that keeps legacy tables while creating permanent `_v2` tables.                                                                                                                                                                             |
| 2026-07-30 | Replaced the REST contract, added rollout and parent-access checks, adapted the offline-evaluation reader to exact revisions, generated OpenAPI clients, and passed 20 focused API and evaluator tests. Mutations reject unsupported fields instead of silently dropping them.                                                |
| 2026-07-30 | Enabled and generated 14 feature-gated dataset MCP tools with dataset scopes, optimistic-concurrency inputs, bounded selectable list responses, and informational wrappers for user-authored content. MCP typecheck, lint, formatting, tool-name checks, generator tests, and focused runtime schema checks pass.             |
| 2026-07-30 | Updated the dataset frontend to use generated contracts for arbitrary JSON values, source and expected outputs, provenance, archive and restore operations, and optimistic concurrency. The full frontend typecheck and 119 focused Jest tests pass.                                                                          |
| 2026-07-30 | Added exact-parent mixed-grant coverage, bounded pagination, and no-op update behavior. The final focused backend suite has 110 passing tests, the frontend typecheck is clean, and 120 focused frontend tests pass.                                                                                                          |
| 2026-07-30 | Completed validation: no migration drift, IDOR coverage passes, full-repository mypy passes for 17,229 files, preflight reports zero failures, and post-generation backend, frontend, and MCP checks pass. The branch is 13 commits behind `master`, whose OpenAPI inputs changed, so merge and regenerate before publishing. |
