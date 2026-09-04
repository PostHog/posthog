---
paths:
  - 'products/tasks/backend/model_catalog.py'
  - 'products/tasks/scripts/build_model_catalog.py'
  - 'products/tasks/frontend/modelCatalog.generated.ts'
  - 'products/desktop/packages/shared/src/model-catalog.generated.ts'
---

`products/tasks/backend/model_catalog.py` is the single definition of a task run's triple: runtime adapter, model, and reasoning effort.
The web composer and the desktop app each read a checked-in TypeScript projection of it, and the backend validates runs against the module itself.

After changing the catalog, run `hogli build:task-model-catalog` and commit both regenerated files.
The command needs no dev stack and takes well under a second, so run it rather than reasoning about whether the output moved.

Never hand-edit `products/tasks/frontend/modelCatalog.generated.ts` or `products/desktop/packages/shared/src/model-catalog.generated.ts`.
A test re-renders both and compares them byte for byte, so an edit that the generator would not produce fails CI rather than shipping.

Adding a model means one row in `MODELS`. Two things do not follow from that row and are worth checking:

- A model gated behind a feature flag also needs an entry in `MODEL_ACCESS_FLAGS` (`products/tasks/backend/constants.py`), which is where the server re-checks entitlement. A picker hiding a model is a convenience, not a gate.
- The catalog names the harness that drives a model. The LLM gateway reports `owned_by`, which names whoever serves it — `cloudflare` and `baseten` for the vendor-served models — so routing a model by its owner puts it on the wrong adapter or drops it entirely.
