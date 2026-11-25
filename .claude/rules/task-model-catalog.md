---
paths:
  - 'products/tasks/backend/model_catalog.py'
  - 'products/tasks/scripts/model_catalog_projection.py'
  - 'products/tasks/frontend/modelCatalog.generated.ts'
  - 'packages/agent/packages/agent-contracts/src/model-catalog.generated.ts'
---

`products/tasks/backend/model_catalog.py` holds the choices around task models: runtime adapters, reasoning tiers and their labels, default models, slider rungs, the model families each product may call and how many versions of a family a picker offers.
It lists no model.
A model's adapter, name, reasoning efforts, context window and price come from its row in the AI gateway listing.
The backend reads the row in `products/tasks/backend/logic/services/model_catalogue.py`, and the desktop app and its agent read it in `packages/agent/packages/agent-contracts/src/model-catalog.ts`.
The web and mobile apps read the backend's answer from `GET /api/projects/:id/tasks/models/`.
A model the gateway does not list has no adapter and cannot run on a product that names families.

After changing the choices, run `hogli build:projections` and commit both regenerated files.
The command needs no dev stack and takes well under a second, so run it rather than reasoning about whether the output moved.

Never hand-edit `products/tasks/frontend/modelCatalog.generated.ts` or `packages/agent/packages/agent-contracts/src/model-catalog.generated.ts`.
`hogli build:projections --check` re-renders both and compares them byte for byte in CI, so an edit that the renderer would not produce fails CI rather than shipping.

A new version of an allowed family needs no change anywhere.
A new family needs an entry in `PRODUCT_MODEL_FAMILIES`. The desktop app reads the families from its bundled projection, so it offers a new family only after its next release.
Two things are worth checking:

- A rollout flag is keyed by gateway family in `MODEL_FAMILY_ACCESS_FLAGS`, so every version and variant of a gated family needs the flag.
  The server's entitlement check and the desktop pickers both read that map.
  The LLM gateway keeps its own copy in `MODEL_ACCESS_FLAGS` (`services/llm-gateway/src/llm_gateway/products/config.py`), because it also serves callers outside this repo.
  Clear both when the rollout reaches everyone: each gate fails closed, so a flag left behind hides the model from anyone the flag service cannot answer for.
- The backend picks the harness from the gateway row's `api_shapes`, never from `owned_by`.
  `owned_by` names whoever serves the model, which is `posthog` for the models PostHog hosts, so routing by owner puts those on the wrong adapter or drops them.
