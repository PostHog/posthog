# Moving code out of ee/

`ee/` is being emptied, one batch at a time.
The target is that no Python stays here.
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

The root `LICENSE` already reads "if that directory exists", so the licensing text survives the directory going away.

## A table does not have to follow its model

`products/access_control/backend/models/access_control.py` declares `app_label = "ee"`, and so do `role.py`, `feature_flag_role_access.py` and `organization_resource_access.py`.
Those models live in a product, under MIT, while their tables stay owned by the `ee` app label and their migrations stay in `ee/migrations/` (`0014`, `0017`, `0025`).

So moving a model out of `ee/` is a code move plus one line in `Meta`.
No `SeparateDatabaseAndState`, no data migration, no table rename.
The precedent is already in the repository and already shipped.

`ee/migrations/` owns 12 tables: `License`, `EnterpriseEventDefinition`, `EnterprisePropertyDefinition`, `ExplicitTeamMembership`, `DashboardPrivilege`, `Role`, `RoleMembership`, `OrganizationResourceAccess`, `FeatureFlagRoleAccess`, `AccessControl`, `SCIMProvisionedUser`, `SCIMRequestLog`.
Those migrations stay, and a minimal app shell stays with them to host the label.

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

## What is in flight

The eight batches that carry no model and needed no new product are open as stack #102736, based on `master` rather than on this branch.
They touch none of the files this PR moves, so the two land in parallel and in either order.

| PR                                                        | Batch                                            | Destination                   |
| --------------------------------------------------------- | ------------------------------------------------ | ----------------------------- |
| [#102727](https://github.com/PostHog/posthog/pull/102727) | `ee/clickhouse/materialized_columns`             | `products/analytics_platform` |
| [#102728](https://github.com/PostHog/posthog/pull/102728) | `ee/tasks/subscriptions`                         | `products/exports`            |
| [#102729](https://github.com/PostHog/posthog/pull/102729) | `ee/clickhouse/views` experiment views and tests | `products/experiments`        |
| [#102730](https://github.com/PostHog/posthog/pull/102730) | `ee/surveys`                                     | `products/surveys`            |
| [#102732](https://github.com/PostHog/posthog/pull/102732) | `ee/admin`                                       | `posthog/admin`               |
| [#102733](https://github.com/PostHog/posthog/pull/102733) | `ee/api/rbac`                                    | `products/access_control`     |
| [#102734](https://github.com/PostHog/posthog/pull/102734) | `ee/support_sidebar_max`                         | `posthog/support_sidebar_max` |
| [#102735](https://github.com/PostHog/posthog/pull/102735) | `ee/benchmarks`                                  | `tools/benchmarks`            |

Those eight remove `ee/surveys`, `ee/api/rbac`, `ee/support_sidebar_max`, `ee/admin` and `ee/benchmarks` from the directory outright.

Three corrections to this plan came out of them:

- **`ee/tasks/subscriptions` goes to `products/exports`, not `products/product_analytics`.** That product is isolated, so the batch needs a facade entry per exposed symbol, and `tach check --interfaces` reports 70. `products/exports` is not isolated, already holds the `Subscription` model and every delivery caller, and needs one `depends_on` line. Ownership does not change: `products/exports` is team-product-analytics too.
- **An `EE_AVAILABLE` guard whose only reason is the directory comes out with the batch.** Materialized columns and the experiments route surface were both gated that way, so a build without the package silently lost them. Removing the guard is a behavior change, not a refactor, and it belongs in the batch's own PR where a reviewer can see it.
- **A setting the batch reads has to move with it.** `MATERIALIZE_COLUMNS_*` and `ANTHROPIC_API_KEY` only resolved while `ee/settings.py` was merged into Django settings, so core code reading them after the move needed them in `posthog/settings/`.

`ee/admin`'s URL block is the one part of a listed batch that did not move. It needs `ADMIN_PORTAL_ENABLED` and `ee/middleware.admin_oauth2_callback`, so it waits on `ee/middleware.py`.

## What moves after that

Each remaining row is one PR, landed as a stack.
"Import sites" counts the lines outside `ee/` that import the batch today.
It measures the width of the rewrite rather than the size of the batch, so a small directory can still be a wide change.
"Core" means `posthog/`, the MIT tree outside `products/`.
The owning team for each batch is in `ee/owners.yaml`, and for a product destination it is that product's `product.yaml`.

### Batches that carry no model

| Batch                               | Files | Import sites | Destination             |
| ----------------------------------- | ----- | ------------ | ----------------------- |
| `ee/partners` (Stripe provisioning) | 31    | 0            | `products/partners`     |
| `ee/vercel`, `ee/api/vercel`        | 34    | 6            | `products/partners`     |
| `ee/api/agentic_provisioning`       | 47    | 3            | `products/provisioning` |

Notes that decide how a row lands:

- Neither `products/partners` nor `products/provisioning` exists yet. Create both with `hogli product:bootstrap`, which scaffolds them already isolated.
- Stripe provisioning and non-Stripe provisioning stay apart. `ee/partners/stripe/api/provisioning` and `ee/api/agentic_provisioning` carry matching module names, and that is not duplication to collapse. Land them as separate batches into separate products.
- `ee/management/commands` is not one batch. Each command rides with the code it drives: `backfill_vercel_secrets` with Vercel, `backfill_scim_request_log_config` with SCIM, and `consume_sqs` with billing. The two `materialize_columns` commands already left with #102727. Anything left over goes to core.

### Batches that carry a model

The model's Python moves and its `Meta` gains `app_label = "ee"`, as in `products/access_control`.
The table and its migrations do not move.

| Batch                                                                                                                                    | Files | Destination                  |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ----- | ---------------------------- |
| `ee/models/event_definition.py`, `ee/models/property_definition.py`, `ee/api/ee_event_definition.py`, `ee/api/ee_property_definition.py` | 4     | `products/event_definitions` |
| `ee/models/explicit_team_membership.py`                                                                                                  | 1     | `products/access_control`    |
| `ee/models/dashboard_privilege.py`                                                                                                       | 1     | `products/dashboards`        |
| `ee/api/scim`, `ee/models/scim_provisioned_user.py`, `ee/models/scim_request_log.py`, `ee/tasks/scim_request_log_cleanup.py`             | 17    | core                         |

The definition models need one decision the others do not.
`EnterpriseEventDefinition` and `EnterprisePropertyDefinition` subclass `EventDefinition` and `PropertyDefinition`, which already live in `products/event_definitions/backend/models`.
The subclasses add the data management columns: `description`, `owner`, `verified`, `verified_by`, `hidden`, `default_columns` and the deprecated tag arrays.

Which model the API uses switches on `EE_AVAILABLE` in `posthog/api/event_definition.py`, not on a per-organization entitlement.
So the columns are gated on the `ee` package being importable, and moving the models out deletes that switch.
Decide what a build without `ee/` should then see before starting this batch.

## Open: can billing and licensing move too?

This is the part with no agreed answer, and it is the only thing between the plan above and an empty `ee/`.

### What is left once every batch above lands

- **The license key.** `ee/models/license.py`, `ee/api/license.py`, `ee/tasks/send_license_usage.py`.
- **Entitlement and quota enforcement.** `ee/api/billing.py`, `ee/api/quota_limits.py`, `ee/billing/`.
- **SAML and SSO.** `ee/api/authentication.py`.
- **Queue plumbing for billing.** `ee/sqs/`, consumed by `ee/billing/queue/BillingConsumer.py` and usage reporting.
- **The app shell.** `ee/apps.py`, `ee/settings.py`, `ee/urls.py`, `ee/middleware.py`, `ee/conftest.py`, `ee/LICENSE`.

All of it is live. The license path in particular:

- `ee/urls.py` mounts `LicenseViewSet` at `api/license`.
- `posthog/cloud_utils.py` reads `License.objects.first_valid()`, and creates a dev license in dev mode.
- `posthog/models/organization.py` reads it to resolve `available_product_features` and the billing plan.
- `posthog/tasks/scheduled.py` runs `clickhouse_send_license_usage` twice a day when `EE_AVAILABLE`, staggered per installation.

The body of that task runs only when `is_cloud()` is false, and `organization.py` takes its features from the billing service when it is true.
So the license key serves self-hosted deployments. `ee/billing` serves cloud, and has 80 import sites, the widest in the directory.

### The question that decides it

Everything else in the plan moves because the Enterprise License was doing no work over it.
Here it does: this is the code that enforces what a customer paid for.
Moving it to `products/billing` relicenses PostHog's own paid-feature enforcement under MIT.

So the discussion is not about mechanics. It is whether we want that enforcement to be MIT.

- **If yes**, `ee/` empties. `products/billing` has no `backend/` today, so it gains one, and the shell moves with the code.
- **If no**, `ee/` keeps exactly this and nothing else, which is a directory that finally matches its own license.

### What the work looks like if the answer is yes

- `products/billing` needs a `backend/`. It holds only `frontend/`, `mcp/`, `skills/` and `package.json` today.
- `License` keeps `app_label = "ee"` in `Meta`, like the access control models, so its table stays.
- `ee/migrations/` and a minimal app shell stay regardless, to host the label for 12 tables. That is the floor unless the label itself is renamed, which is a separate and much larger job.
- The `EE_AVAILABLE` switch loses its meaning. It has 79 references outside `ee/` in non-test code, across `posthog/api`, `posthog/clickhouse`, `posthog/hogql_queries` and more, alongside 159 `from ee.` import sites. Most exist to tolerate the package being absent, which stops being possible.
- `ee/LICENSE` and the `ee/` clause in the root `LICENSE` come out. The root file already says "if that directory exists".

## Rules while this is in progress

- **Do not add new code to `ee/`.** New code belongs in the product that owns it. Put it here only if it is gated on a license or an entitlement, and say which one in the PR.
- **One batch per PR.** A batch is a directory with one owner.
- **A model's table stays.** Move the Python, add `app_label = "ee"` to `Meta`, leave `ee/migrations/` alone.
- **Land the stack bottom-first, through the merge queue.** See `/stacking-prs` and `/merging-prs`.
- **Expect the move to surface couplings, not create them.** `tach.toml` allows most products to depend on `ee`, so an import of `ee/hogai` from another product needed no declaration. Once the code sits under `products.posthog_ai`, 22 modules had to declare that dependency. The same will happen for each batch, and the resulting diff in `tach.toml` is the point rather than a side effect.
- **Check the ruff config for the destination.** `products/ruff.toml` enables `ANN` rules that the root config does not, so code moving from `ee/` into a product starts failing lint on arrival. `products/ruff.toml` carries a list of temporary per-directory exemptions; add the batch there rather than annotating it inside the move.
