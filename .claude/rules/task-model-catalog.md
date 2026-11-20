---
paths:
  - 'products/tasks/backend/model_catalog.py'
  - 'products/tasks/scripts/model_catalog_projection.py'
  - 'products/tasks/frontend/modelCatalog.generated.ts'
  - 'packages/agent/packages/agent-contracts/src/model-catalog.generated.ts'
---

`products/tasks/backend/model_catalog.py` holds the model rows the web composer and the desktop app read through two checked-in TypeScript projections, and the choices around models: default models, slider rungs and effort labels.
The backend reads none of the rows.
It takes a model's adapter, name, reasoning efforts and cost from the model's row in the AI gateway listing (`products/tasks/backend/logic/services/model_catalogue.py`).
It takes which models a product may call and offer from the product's model families (`products/tasks/backend/logic/services/gateway_model_pin.py`).
A model the gateway does not list has no adapter and cannot run on a product that names families.

After changing the catalog, run `hogli build:projections` and commit both regenerated files.
The command needs no dev stack and takes well under a second, so run it rather than reasoning about whether the output moved.

Never hand-edit `products/tasks/frontend/modelCatalog.generated.ts` or `packages/agent/packages/agent-contracts/src/model-catalog.generated.ts`.
`hogli build:projections --check` re-renders both and compares them byte for byte in CI, so an edit that the renderer would not produce fails CI rather than shipping.

A new version of an allowed family needs no backend change.
Add a row to `MODELS` so the web composer and the desktop app list it too.
Two things do not follow from that row and are worth checking:

- A rollout flag is set in two places.
  The server's entitlement check reads `MODEL_FAMILY_ACCESS_FLAGS` in `gateway_model_pin.py`, keyed by gateway family, so every version and variant of a gated family needs the flag.
  The web composer and the desktop app read the row's `access_flag` to decide what a picker shows.
  The LLM gateway keeps its own copy in `MODEL_ACCESS_FLAGS` (`services/llm-gateway/src/llm_gateway/products/config.py`), because it also serves callers outside this repo.
  Clear all of them when the rollout reaches everyone: each gate fails closed, so a flag left behind hides the model from anyone the flag service cannot answer for.
- The backend picks the harness from the gateway row's `api_shapes`, never from `owned_by`.
  `owned_by` names whoever serves the model, which is `posthog` for the models PostHog hosts, so routing by owner puts those on the wrong adapter or drops them.
