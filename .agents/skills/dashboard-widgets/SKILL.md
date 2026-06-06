---
name: dashboard-widgets
description: >
  Guides PostHog engineers through dashboard widget platform work in the repo — ship a
  new widget_type (WIDGET_REGISTRY, catalog, run_widgets, WidgetCard) or change an
  existing shipped type (config, query, layout, RBAC). Use when implementing or
  modifying dashboard widget types such as error_tracking_list or session_replay_list.
  New types require widget-intake spec confirmation before coding. Do not use for MCP
  batch-add of existing types or adding tiles to a dashboard.
---

# Managing dashboard widgets

For **PostHog engineers** working on dashboard **widget tiles** in the repo.

Human overview: [`products/dashboards/CONTRIBUTING.md`](../../../products/dashboards/CONTRIBUTING.md)

**In scope:** widget tiles (`widget_id` on `DashboardTile`) — ship new types or change shipped types.

**Out of scope:** adding an existing type to a dashboard (MCP `dashboard-widget-catalog-list` → `dashboard-widgets-batch-add`); insight tiles, text cards, button tiles.

## 1. Route first

| Request                                                                | Path       | Start here                                                         |
| ---------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------ |
| New **`widget_type`** that does not exist                              | **Ship**   | [§2 Ship a new type](#2-ship-a-new-widget_type) — intake mandatory |
| Change a **shipped** type (config, query, UI, layout, RBAC, deprecate) | **Update** | [§3 Update a shipped type](#3-update-a-shipped-type) — skip intake |
| Add existing type to a dashboard                                       | —          | MCP only — not this skill                                          |

Shipped types (code truth): [architecture.md § Shipped types](references/architecture.md#shipped-types-source-of-truth).

## 2. Ship a new widget_type

### Intake — ask before coding

**Mandatory for new types only.** Read [widget-intake.md](references/widget-intake.md) and:

1. Infer from the request ([§2.2 defaults](#22-infer--defaults)).
2. Ask **one batched follow-up** for gaps — max 6 questions ([question bank](references/widget-intake.md#ask-when-not-stated)).
3. Post the [spec table](references/widget-intake.md#spec-fields-to-lock); get confirmation before checklist §1.

### 2.2 Infer — defaults

Apply silently; ask only when the request is silent on a [question-bank](references/widget-intake.md) row.

| Derive              | Default                                                                       |
| ------------------- | ----------------------------------------------------------------------------- |
| `widget_type`       | Unique `snake_case` from label                                                |
| `groupId`           | Same as sibling in that product area                                          |
| Copy spine          | `error_tracking_list` / `frontend/widgets/error_tracking/`                    |
| Copy spine (replay) | `session_replay_list` when recordings, throttles, or session RBAC             |
| Config              | List: `limit`, `orderBy`, `orderDirection`, `dateRange`, `filterTestAccounts` |
| RBAC                | Same `required_product_access` as sibling                                     |
| Layout              | Sibling `defaultLayout`; explicit `minH` for dense lists                      |
| Setup gating        | Match sibling pattern                                                         |
| `sharedPlaceholder` | Platform default                                                              |

### 2.3 Execute

After spec confirmation → [checklist-new-widget-type.md](references/checklist-new-widget-type.md) **§1 → §8**. §5b / §9 after MVP tests green.

## 3. Update a shipped type

**Skip intake.** The `widget_type` already exists — identify it from the request or `EXPECTED_WIDGET_TYPES` in `widget_registry.py`.

1. Read [managing-existing-widgets.md](references/managing-existing-widgets.md) — use the **"What kind of change?"** routing table for primary files.
2. Confirm with the engineer: which shipped type, what changes, and whether stored tiles need backward-compatible config migration.
3. Follow linked references from that table (composition, layout, permissions, availability) — do not re-read the new-type checklist.

**Cannot change in place:** `widget_type` string on existing rows; stored `w`/`h` for tiles already on dashboards when catalog defaults change.

**New visualization kind** = ship a new type ([§2](#2-ship-a-new-widget_type)), not an update.

## 4. Platform invariants

Both paths:

1. **RBAC registry-driven** — no `widget_type` branches in `dashboard.py`. [permissions-and-sharing.md § Product RBAC](references/permissions-and-sharing.md#product-rbac)
2. **One `widget_type` everywhere** — registries + both catalogs + FE registry; variants share `groupId` only.
3. **Per-type code in product paths** — not in platform shells. [architecture.md § Platform files](references/architecture.md#platform-files--do-not-branch-per-type)
4. **WidgetCard compound pattern** — [composition.md](references/composition.md)
5. **Config PATCH = JSONField** — typed OpenAPI in `widget_openapi_serializers.py` only.

New `widget_type` strings need **no migration** — register registries + catalogs only.

## 5. Companion skills

| Skill                          | When                                                  |
| ------------------------------ | ----------------------------------------------------- |
| `improving-drf-endpoints`      | `widget_openapi_serializers.py` or serializer changes |
| `writing-kea-logics`           | `edit*WidgetModalLogic.ts` or `dashboardLogic.tsx`    |
| `django-migrations`            | `DashboardWidget` / `DashboardTile` schema only       |
| `adopting-generated-api-types` | Tile PATCH in `frontend/utils.ts`                     |

## 6. Verify

**Ship (MVP):**

```bash
hogli test products/dashboards/backend/api/test/test_run_widgets.py
hogli test products/dashboards/backend/api/test/test_dashboard_widgets.py
hogli test products/dashboards/frontend/widgets/registry.test.tsx
```

**Ship (before PR):** [checklist §8](references/checklist-new-widget-type.md#8-tests) + `hogli build:openapi`.

**Update:** tests for the area you touched — at minimum:

```bash
hogli test products/dashboards/backend/api/test/test_run_widgets.py   # if run_* / validate_* changed
hogli test products/dashboards/frontend/widgets/                      # if Component / modal changed
hogli build:openapi                                                   # if config OpenAPI / serializers changed
```

See [managing-existing-widgets.md](references/managing-existing-widgets.md) routing table **Also check** column per change type.

## Reference appendix

| Topic                   | Doc                                                                     |
| ----------------------- | ----------------------------------------------------------------------- |
| Intake (new types only) | [widget-intake.md](references/widget-intake.md)                         |
| New type checklist      | [checklist-new-widget-type.md](references/checklist-new-widget-type.md) |
| Update shipped type     | [managing-existing-widgets.md](references/managing-existing-widgets.md) |
| Architecture            | [architecture.md](references/architecture.md)                           |
| WidgetCard / edit modal | [composition.md](references/composition.md)                             |
| Tile min/max            | [layout-and-ux.md](references/layout-and-ux.md)                         |
| RBAC / sharing          | [permissions-and-sharing.md](references/permissions-and-sharing.md)     |
| Setup gates             | [availability-and-gating.md](references/availability-and-gating.md)     |
| MCP after ship          | [mcp.md](references/mcp.md)                                             |
