---
name: placing-product-frontend-code
description: >
  Decide which tree a frontend file belongs in — `products/<name>/frontend/` or
  `frontend/src/scenes/<name>/` — and explain why the boundary is real rather than stylistic.
  Use when adding a new scene, component, or logic file for a product; when creating a new
  directory under `frontend/src/scenes/`; when a product has UI in both trees and you need to
  know which side to extend; or when moving a scene into its product. Covers the merge-queue
  lane cost of the split, the measurement showing a dependency graph cannot substitute for the
  path signal, and a report script that shows how far each product's move has gone.
---

# Placing product frontend code

**A product's UI belongs in `products/<name>/frontend/`, not `frontend/src/scenes/<name>/`.**

About 18 products still have UI in both trees, so "there's already a folder in `scenes/`" is not evidence that a new file belongs there. Check before you add.

```sh
# Where does one directory stand?
python3 .agents/skills/placing-product-frontend-code/scripts/scene_product_split.py data-warehouse

# Every scene dir with a product counterpart, most migrated first
python3 .agents/skills/placing-product-frontend-code/scripts/scene_product_split.py
```

The script is advisory and read-only — no baseline, no exit code to satisfy. It counts hand-written `.ts`/`.tsx` on each side, skipping `generated/` (orval writes those, so they are not migration progress).

## Deciding where a file goes

| Situation                                                                             | Where it goes                                                                                                      |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `products/<name>/frontend/` holds as much or more than `scenes/<name>/`               | `products/<name>/frontend/` — the scenes copy is a remnant                                                         |
| The move is under way but early                                                       | `products/<name>/frontend/`, and move the files the new code touches if that is cheap                              |
| `products/<name>/` exists, no `scenes/<name>/` yet                                    | `products/<name>/frontend/` — never create the scenes directory                                                    |
| No product directory at all, and the feature is product-shaped                        | Bootstrap the product: `bin/hogli product:bootstrap <name>`, see [products/README.md](../../../products/README.md) |
| App-level scene — `settings`, `onboarding`, `billing`, `max`, `error-tracking` shells | `frontend/src/scenes/` is correct; these have nowhere else to go                                                   |

The last row is the reason this is a skill and not a lint rule: deciding whether a new directory is a product or an app-level scene is a judgment call, and a check script that guesses gets it wrong on `onboarding` and `settings`.

Migrating an existing scene wholesale is welcome and is the point of the convention. Expect that PR to report every merge-queue target once, because scenes register in `products/<name>/manifest.tsx` — a one-time cost per migration.

## Why the directory is a real boundary

`.github/scripts/trunk-impacted-targets.js` assigns merge-queue lanes by path.

- A change anywhere under `frontend/` reports `fe:core` plus every `fe:product:*` target, so it serializes against every other frontend PR in the queue.
- A change confined to `products/<name>/frontend/` reports one target.

The obvious fix — narrow lanes with a frontend dependency graph instead of paths — was measured and does not work. A static import graph over the frontend (8430 files, 43924 edges) puts **2226 modules in a single strongly connected component**, 27% of the graph, spanning 31 products. Every member of an SCC has identical reverse-reachability by definition, so reverse-reachability from any file under `frontend/src` reaches 73 of 79 products — a leaf tab component five levels into the replay player gives the byte-identical answer to `types.ts`. Cutting all 498 `lib/**` → `scenes|products` back-edges moved it from 6918 to 6909 modules: hundreds of redundant cycles, not one bad edge.

`bin/find-affected-stories` already concedes the same thing by listing `frontend/src/lib/` as a full-run invalidator.

So path is the only signal that discriminates, and moving files is the only thing that narrows a lane. Note what this does and does not buy: merge-queue parallelism, not decoupling — the import graph stays as tangled as it was.

## Related

- [products/README.md](../../../products/README.md) — product layout and setup
- [products/architecture.md](../../../products/architecture.md) — DTOs, facades, isolated testing
- [frontend/src/AGENTS.md](../../../frontend/src/AGENTS.md) — the rest of the frontend guide
