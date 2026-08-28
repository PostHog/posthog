# Generated notebook widgets

Notebooks can generate interactive widgets from instructions and the notebook's SQL and Python dataframe context.

- Generation runs as a durable background job. The notebook shows its phase, elapsed time, cancellation, and terminal errors. Queued jobs stop immediately when canceled.
- Successful source, generated titles, prompts, models, and dataframe contracts are stored as immutable versions.
- People can inspect history and source, request source changes, restore an earlier version, improve the current widget, or regenerate it.
- A new widget uses “visualize the data in this notebook in weird and wonderful ways” when its instruction field is left empty.
- Running a widget re-runs only its connected SQL and Python data cells in dependency order. It reloads the existing preview without generating a new version.
- A generated preview never starts automatically unless the viewer already trusts its exact immutable build, every widget in the notebook, or every widget in the project.
- Every ready build exposes the SHA-256 of its frozen Canvas artifact manifest. “Run widget” records consent for that hash, so source or artifact changes require a new decision.
- “View source” remains available before a widget runs and reads the source belonging to the selected historical version.
- Every dataframe must have a completed run before generation. Each preview load pins permission-checked pages to one run and reads at most 5,000 rows without sending values to the model.
- Notebook-managed Canvas artifacts use a restricted source policy. Signed artifact URLs can render them, but the ordinary Canvas API cannot list or edit them.
- `<Widget>` is the canonical notebook markdown tag. Legacy `<GeneratedWidget>` and `<GenUI>` tags normalize to it while preserving widget identity.
- Organizations must approve AI data processing before a job is queued and when its worker starts.
- Production creation and data-frame reads require the `notebook-generated-widgets` feature flag. Keep it disabled until the generated-code data boundary and mixed-version Canvas rollout are approved.
- Artifact URLs use Django's rotating `SECRET_KEY` values by default. Deployments can set `CANVAS_ARTIFACT_SIGNING_KEYS` for independent rotation.

“Widget” is the umbrella term. Data visualizations are one possible widget type.

## Generated-code trust model

Generated widget source is arbitrary React and JavaScript. It is not a restricted widget schema, and PostHog does not claim to make it safe by parsing an AST, matching source text, or blocking selected syntax. JavaScript can construct equivalent behavior dynamically, so source-shape validation would create a false security boundary while breaking legitimate widgets.

The execution decision belongs to the viewer:

1. Canvas builds an immutable artifact and records a SHA-256 over the complete frozen manifest.
2. The notebook API returns that build hash with both current status and historical versions.
3. The frontend does not mount the artifact iframe until the current viewer trusts that exact hash or a broader scope.
4. “Run widget” trusts only that hash. A rebuilt or changed artifact has a different hash and stops at the gate again.
5. Notebook and project trust are explicit conveniences. They cover future builds in that scope, including builds created by other editors.

Trust choices are stored in the browser, partitioned by PostHog user ID. An anonymous viewer can run an exact build for the current browser session but cannot save notebook or project trust. This client-side consent state is a user-experience boundary; server authorization remains the data boundary.

There is intentionally no “trust widgets by this author” option. An author is not the sole authority over a collaborative notebook node: another editor can change its instructions, regenerate it, restore a version, or otherwise replace the artifact after the original author created it. Binding trust to an immutable build is stable; binding it to a mutable ownership label is not.

Same-team scoping reduces exposure but does not eliminate realistic risk. The cases worth guarding against include:

- an editor intentionally adding a deceptive or disruptive widget for teammates;
- a compromised editor account regenerating an existing, previously benign node;
- prompt injection or a generator/supply-chain defect producing behavior nobody intended;
- a future copied or shared notebook carrying active content into a context where the viewer did not create it;
- a trusted notebook or project changing membership or editorial ownership over time.

The sandboxed cross-origin iframe, Canvas CSP, signed artifact route, capability manifest, and permission-checked dataframe bridge limit blast radius. They do not turn arbitrary JavaScript into trusted code. Runtime navigation interception is defense-in-depth for preview reliability, not a security claim.

An AI source reviewer can later add useful evidence before consent. It must review the source and capability manifest associated with the exact build hash, display findings to the viewer, and never silently grant trust. Review is advisory because generated and obfuscated JavaScript cannot be proven safe by a model or static analysis.
