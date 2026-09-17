# Moving code out of ee/

`ee/` is being emptied into `products/` and core, one batch at a time.
This file records the plan, the order, and the rules that apply while it is in progress.

## Why

`ee/` is a license boundary drawn by directory path.
The root `LICENSE` puts everything under `ee/` on the Enterprise License and everything else on MIT.
That path is the only thing the split is based on, so a file's license here is a function of where it sits, not of what it does.

Most of what sits here does not need that boundary.
Of the 230 non-test Python files left, 10 touch the license key or the entitlement check.
The rest is product code that landed here for historical reasons and then stayed, because moving it costs more than leaving it.

Leaving it has its own cost.
`ee/` has no owner of its own: `ee/owners.yaml` sets `owners: []` and routes single directories to five different teams.
A change here runs the full Django backend suite rather than one product's selective tests, and every team that works in the directory pays for that.

## What the Enterprise License actually covers

No third-party license forces any file into `ee/`.
Nothing in this tree is vendored, and no dependency reached only from here is copyleft.
A copyleft dependency could not produce this outcome anyway: it would demand its own terms, which `ee/LICENSE` is incompatible with.

So the boundary is a commercial decision, and moving a file across it is also a commercial decision.
**A file that leaves `ee/` becomes MIT.**
Get that agreed for the batch before the move, not during review of it.
For code with no entitlement check in it, the practical effect is small, but the decision is still not a refactoring one.

## What moved first

`ee/hogai` moved to `products/posthog_ai/backend/hogai`.

That batch went first because it was the largest and the least entangled:

- 529 files, 57% of the directory.
- No Django models and no migrations, so no database state to move.
- The models it reads already lived in `products/posthog_ai/backend/models`.
- `ee/hogai` and `products/posthog_ai` were already owned by the same team, so one team reviewed the whole move.

The same PR deletes `ee/session_recordings`.
It held one snapshot file whose test class lives in `posthog/session_recordings/queries/test/listing_recordings/`.
All 41 of its snapshots are a subset of the 287 in that directory's own file, so it was a stale copy.

## What moves next

Each row is one PR, landed as a stack on top of the `hogai` move.
"Import sites" counts the lines outside `ee/` that import the batch today.
It measures the width of the rewrite rather than the size of the batch, so a small directory can still be a wide change.
"Core" means `posthog/`, the MIT tree outside `products/`.
The owning team for each batch is in `ee/owners.yaml`, and for a product destination it is that product's `product.yaml`.

### Code-only batches

These carry no Django model, so they are a rename plus an import rewrite.

| Batch                                              | Files | Import sites | Destination                   |
| -------------------------------------------------- | ----- | ------------ | ----------------------------- |
| `ee/surveys`                                       | 2     | 1            | `products/surveys`            |
| `ee/api/rbac`                                      | 1     | 0            | `products/access_control`     |
| `ee/support_sidebar_max`                           | 5     | 0            | core                          |
| `ee/admin`                                         | 2     | 2            | core                          |
| `ee/clickhouse/materialized_columns`               | 7     | 55           | `products/analytics_platform` |
| `ee/clickhouse/views` experiment views and tests   | ~10   | 9            | `products/experiments`        |
| `ee/tasks/subscriptions`                           | 8     | 22           | `products/product_analytics`  |
| `ee/benchmarks`                                    | 6     | 0            | `tools/`                      |
| `ee/partners/stripe`, `ee/vercel`, `ee/api/vercel` | 65    | 3            | `products/partners`           |
| `ee/api/agentic_provisioning`                      | 47    | 0            | `products/provisioning`       |

Notes that decide how a row lands:

- `ee/clickhouse/materialized_columns` has 55 import sites against 7 files. It is a cheap move that touches many call sites, so land it alone.
- `ee/tasks/subscriptions` goes to `products/product_analytics`, which owns it. Its callers do not live there: 8 of the 9 import sites are in `products/exports`, so that product's imports change in the same PR.
- `ee/benchmarks` has to still run after the move. It is an asv suite, and `asv.conf.json`, `measure.sh` and the benchmark discovery paths all name the current location.
- Neither `products/partners` nor `products/provisioning` exists yet. Create both with `hogli product:bootstrap`, which scaffolds them already isolated.
- `ee/partners/stripe/api/provisioning` and `ee/api/agentic_provisioning` are parallel implementations of the same job, down to matching `analytics`, `authentication`, `constants`, `exceptions`, `region_proxy` and `serializers` modules. Decide whether they consolidate before the split, not after.
- `ee/management/commands` is not one batch. Each command rides with the code it drives: the two `materialize_columns` commands with materialized columns, `backfill_vercel_secrets` with Vercel, `backfill_scim_request_log_config` with SCIM, and `consume_sqs` with billing. Anything left over goes to core.

### Batches that move database state

These carry models in the `ee` app, so the table stays while the Python moves.
Follow `/django-migrations` and the `SeparateDatabaseAndState` pattern in `products/README.md`.
They are harder per file than the `hogai` move, not easier.

| Batch                                                                                                                                    | Files | Destination                  |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ----- | ---------------------------- |
| `ee/models/event_definition.py`, `ee/models/property_definition.py`, `ee/api/ee_event_definition.py`, `ee/api/ee_property_definition.py` | 4     | `products/event_definitions` |
| `ee/models/explicit_team_membership.py`                                                                                                  | 1     | `products/access_control`    |
| `ee/models/dashboard_privilege.py`                                                                                                       | 1     | `products/dashboards`        |
| `ee/api/scim`, `ee/models/scim_provisioned_user.py`, `ee/models/scim_request_log.py`, `ee/tasks/scim_request_log_cleanup.py`             | 17    | core                         |

The definition models need more than a table move.
`EnterpriseEventDefinition` and `EnterprisePropertyDefinition` subclass `EventDefinition` and `PropertyDefinition`, which already live in `products/event_definitions/backend/models`.
The subclasses add the data management columns: `description`, `owner`, `verified`, `verified_by`, `hidden`, `default_columns` and the deprecated tag arrays.
Django multi-table inheritance gives each subclass its own table with a `parent_link` to the product's table, created in `ee/migrations/0004`.

Which model the API uses switches on `EE_AVAILABLE` in `posthog/api/event_definition.py`, not on a per-organization entitlement.
So the columns are gated on the `ee` package being importable, and moving the models out deletes that switch.
Decide what a build without `ee/` should then see before starting this batch.

## What stays

`ee/` does not go away. These stay under the Enterprise License:

- `ee/models/license.py`, `ee/api/license.py`, `ee/tasks/send_license_usage.py`. The license key itself.
- `ee/api/billing.py`, `ee/api/quota_limits.py`, `ee/billing/`. Entitlement and quota enforcement, cloud-only. `ee/billing` alone has 80 import sites.
- `ee/api/authentication.py`. SAML and SSO, which are entitled features.
- `ee/sqs/`. Queue plumbing for billing. Its consumers are `ee/billing/queue/BillingConsumer.py` and usage reporting, so it follows billing.
- `ee/migrations/`. The `ee` app label owns these tables. The migrations stay wherever the app label stays, whatever moves out of the Python tree.
- `ee/LICENSE`, `ee/apps.py`, `ee/settings.py`, `ee/urls.py`, `ee/middleware.py`, `ee/conftest.py`. The app itself.

## Rules while this is in progress

- **Do not add new code to `ee/`.** New code belongs in the product that owns it. Put it here only if it is gated on a license or an entitlement, and say which one in the PR.
- **One batch per PR.** A batch is a directory with one owner. Do not combine a code-only batch with one that moves a model.
- **Do not renumber or move `ee/migrations`.**
- **Land the stack bottom-first, through the merge queue.** See `/stacking-prs` and `/merging-prs`.
- **Expect the move to surface couplings, not create them.** `tach.toml` allows most products to depend on `ee`, so an import of `ee/hogai` from another product needed no declaration. Once the code sits under `products.posthog_ai`, 22 modules had to declare that dependency. The same will happen for each batch, and the resulting diff in `tach.toml` is the point rather than a side effect.
- **Check the ruff config for the destination.** `products/ruff.toml` enables `ANN` rules that the root config does not, so code moving from `ee/` into a product starts failing lint on arrival. `products/ruff.toml` carries a list of temporary per-directory exemptions; add the batch there rather than annotating it inside the move.
