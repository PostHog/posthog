# Generated notebook widgets

Notebooks can generate interactive widgets from instructions and the notebook's SQL and Python dataframe context.

- Generation runs as a durable background job. The notebook shows its phase, elapsed time, cancellation, and terminal errors.
- Successful source, prompts, models, and dataframe contracts are stored as immutable versions.
- People can inspect history, restore an earlier state as a new version, improve the current widget, regenerate it, or save a manual source edit.
- The Notebooks **Widgets** tab lists reusable widget resources, version counts, and usage separately from their notebook placements.
- Notebook-managed Canvas artifacts use a restricted source policy and cannot be edited through the ordinary Canvas API.

“Widget” is the umbrella term. Data visualizations are one possible widget type.

Future reuse should offer **Add a copy** by default and **Link to shared widget** explicitly. Copies have independent history. Linked placements should pin a version by default and bind logical input slots to compatible frames in the destination notebook.
