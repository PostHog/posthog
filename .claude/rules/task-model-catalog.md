---
paths:
  - 'products/tasks/backend/model_catalog.py'
  - 'products/tasks/scripts/model_catalog_projection.py'
  - 'products/tasks/frontend/modelCatalog.generated.ts'
  - 'packages/agent/packages/agent-contracts/src/model-catalog.generated.ts'
---

`products/tasks/backend/model_catalog.py` lists the models a task run may pick and the choices around them: default models, slider rungs and effort labels.
The web composer and the desktop app each read a checked-in TypeScript projection of it.
The backend does not read a model's adapter, name, reasoning efforts or cost from this file.
It reads them from the model's row in the AI gateway listing (`products/tasks/backend/logic/services/model_catalogue.py`), and a model the gateway does not list has none.

After changing the catalog, run `hogli build:projections` and commit both regenerated files.
The command needs no dev stack and takes well under a second, so run it rather than reasoning about whether the output moved.

Never hand-edit `products/tasks/frontend/modelCatalog.generated.ts` or `packages/agent/packages/agent-contracts/src/model-catalog.generated.ts`.
`hogli build:projections --check` re-renders both and compares them byte for byte in CI, so an edit that the renderer would not produce fails CI rather than shipping.

Adding a model means one row in `MODELS`. Two things do not follow from that row and are worth checking:

- A model gated behind a feature flag carries the flag in its `access_flag`, which every picker and the server's entitlement check read.
  The LLM gateway keeps its own copy in `MODEL_ACCESS_FLAGS` (`services/llm-gateway/src/llm_gateway/products/config.py`), because it also serves callers outside this repo.
  Clear both when the rollout reaches everyone: each gate fails closed, so a flag left behind hides the model from anyone the flag service cannot answer for.
- The backend picks the harness from the gateway row's `api_shapes`, never from `owned_by`.
  `owned_by` names whoever serves the model, which is `posthog` for the models PostHog hosts, so routing by owner puts those on the wrong adapter or drops them.
