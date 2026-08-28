# Generated notebook widgets

Notebooks can generate interactive widgets from instructions and the notebook's SQL and Python dataframe context.

- Generation runs as a durable background job. The notebook shows its phase, elapsed time, cancellation, and terminal errors. Queued jobs stop immediately when canceled.
- Successful source, generated titles, prompts, models, and dataframe contracts are stored as immutable versions.
- People can inspect history and source, request source changes, restore an earlier version, improve the current widget, or regenerate it.
- A new widget uses “visualize the data in this notebook in weird and wonderful ways” when its instruction field is left empty.
- Running a widget re-runs only its connected SQL and Python data cells in dependency order. It reloads the existing preview without generating a new version.
- Every dataframe must have a completed run before generation. Each preview load pins permission-checked pages to one run and reads at most 5,000 rows without sending values to the model.
- Notebook-managed Canvas artifacts use a restricted source policy. Signed artifact URLs can render them, but the ordinary Canvas API cannot list or edit them.
- `<Widget>` is the canonical notebook markdown tag. Legacy `<GeneratedWidget>` and `<GenUI>` tags normalize to it while preserving widget identity.
- Organizations must approve AI data processing before a job is queued and when its worker starts.
- Production creation and data-frame reads require the `notebook-generated-widgets` feature flag. Keep it disabled until the generated-code data boundary and mixed-version Canvas rollout are approved.
- Local artifact URLs use `CANVAS_ARTIFACT_SIGNING_KEYS` from `.env.development`.

“Widget” is the umbrella term. Data visualizations are one possible widget type.
