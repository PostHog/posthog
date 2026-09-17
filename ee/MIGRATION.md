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
`ee/` has no owner of its own: `ee/owners.yaml` sets `owners: []` and routes single directories to six different teams.
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

## What moves next

Each row is one PR, landed as a stack on top of the `hogai` move.
"Inbound" counts import sites outside `ee/` that reference the batch today.

Destinations are proposals.
The owning team decides where its code lands, and may split a row further.

### Code-only batches

These carry no Django model, so they are a rename plus an import rewrite.

| Batch                                              | Files | Inbound | Proposed destination                               | Owner                   |
| -------------------------------------------------- | ----- | ------- | -------------------------------------------------- | ----------------------- |
| `ee/session_recordings`                            | 1     | 0       | `products/replay`                                  | team-replay             |
| `ee/surveys`                                       | 2     | 1       | `products/surveys`                                 | conversations           |
| `ee/support_sidebar_max`                           | 5     | 0       | `products/posthog_ai`                              | team-self-driving       |
| `ee/admin`, `ee/management`, `ee/sqs`              | 10    | 2       | core, or the owning product                        | unowned                 |
| `ee/partners/stripe`, `ee/vercel`, `ee/api/vercel` | 65    | 3       | one provisioning home                              | unowned                 |
| `ee/api/agentic_provisioning`                      | 47    | 0       | same home as the row above                         | unowned                 |
| `ee/clickhouse/views` experiment views and tests   | ~10   | low     | `products/experiments`                             | team-product-analytics  |
| `ee/clickhouse/materialized_columns`               | 7     | 55      | `products/analytics_platform`                      | team-analytics-platform |
| `ee/tasks/subscriptions`                           | 8     | 22      | `products/exports` or `products/product_analytics` | team-product-analytics  |
| `ee/api/rbac`                                      | 1     | low     | `products/access_control`                          | unowned                 |
| `ee/benchmarks`                                    | 6     | 0       | `tools/`                                           | unowned                 |

`ee/clickhouse/materialized_columns` has a high inbound count against a small file count.
It is a cheap move that touches many call sites, so it is better landed alone than bundled.

### Batches that move database state

These carry models in the `ee` app, so the table has to stay put while the Python moves.
Follow `/django-migrations` and the `SeparateDatabaseAndState` pattern in `products/README.md`.
They are not "much easier" than the `hogai` move; they are harder per file.

| Batch                                                                                                                                    | Files | Inbound    | Proposed destination                             | Owner                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ----- | ---------- | ------------------------------------------------ | ---------------------------------------- |
| `ee/models/event_definition.py`, `ee/models/property_definition.py`, `ee/api/ee_event_definition.py`, `ee/api/ee_property_definition.py` | 4     | part of 58 | `products/event_definitions`                     | unowned                                  |
| `ee/models/explicit_team_membership.py`, `ee/models/dashboard_privilege.py`                                                              | 2     | part of 58 | `products/access_control`, `products/dashboards` | unowned                                  |
| `ee/api/scim`, `ee/models/scim_provisioned_user.py`, `ee/models/scim_request_log.py`, `ee/tasks/scim_request_log_cleanup.py`             | 17    | low        | core org management                              | team-security owns `ee/api/scim/auth.py` |

## What stays

`ee/` does not go away. These stay under the Enterprise License:

- `ee/models/license.py`, `ee/api/license.py`, `ee/tasks/send_license_usage.py`. The license key itself.
- `ee/api/billing.py`, `ee/api/quota_limits.py`, `ee/billing/`. Entitlement and quota enforcement, cloud-only. `ee/billing` alone has 80 inbound import sites.
- `ee/api/authentication.py`. SAML and SSO, which are entitled features.
- `ee/migrations/`. The `ee` app label owns these tables. The migrations stay wherever the app label stays, whatever moves out of the Python tree.
- `ee/LICENSE`, `ee/apps.py`, `ee/settings.py`, `ee/urls.py`, `ee/middleware.py`, `ee/conftest.py`. The app itself.

## Rules while this is in progress

- **Do not add new code to `ee/`.** New code belongs in the product that owns it. Put it here only if it is gated on a license or an entitlement, and say which one in the PR.
- **One batch per PR.** A batch is a directory with one owner. Do not combine a code-only batch with one that moves a model.
- **Do not renumber or move `ee/migrations`.**
- **Land the stack bottom-first, through the merge queue.** See `/stacking-prs` and `/merging-prs`.
- **Expect the move to surface couplings, not create them.** `tach.toml` allows most products to depend on `ee`, so an import of `ee/hogai` from another product needed no declaration. Once the code sits under `products.posthog_ai`, 22 modules had to declare that dependency. The same will happen for each batch, and the resulting diff in `tach.toml` is the point rather than a side effect.
- **Check the ruff config for the destination.** `products/ruff.toml` enables `ANN` rules that the root config does not, so code moving from `ee/` into a product starts failing lint on arrival. `products/ruff.toml` carries a list of temporary per-directory exemptions; add the batch there rather than annotating it inside the move.
