# Generated notebook widgets

Notebooks can generate interactive widgets from instructions and the notebook's SQL and Python dataframe context.

- Generation runs as a durable background job. The notebook shows its phase, elapsed time, cancellation, and terminal errors. Queued jobs stop immediately when canceled.
- Successful source, generated titles, prompts, models, dataframe contracts, and security reviews are stored as immutable versions.
- People can inspect history and source, request source changes, restore an earlier version, improve the current widget, or regenerate it.
- A new widget uses “visualize the data in this notebook in weird and wonderful ways” when its instruction field is left empty.
- Running a widget re-runs only its connected SQL and Python data cells in dependency order. It reloads the existing preview without generating a new version.
- A fast model reviews the exact generated source before Canvas publishes it. A review failure stops publication.
- A preview starts automatically when the review finds no concrete issues. Findings and legacy unreviewed versions stop at a gate that shows the review result and links to the source.
- Every ready build exposes the SHA-256 of its frozen Canvas artifact manifest. “Run widget anyway” records consent for that hash, so source or artifact changes require a new decision.
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

Generation and execution use two separate checks:

1. Existing static validation rejects unsupported imports, direct network APIs, dynamic imports, inline scripts, and undeclared dataframe reads.
2. A fast model reviews the validated source as untrusted input. It looks for concrete exfiltration, deception, dynamic execution, browser access, side effects, and resource-abuse risks that static checks cannot reliably identify.
3. The immutable widget version stores the highest severity, summary, findings, review model, review-instruction version, and review time. Restoring a version carries forward the review of that exact source.
4. Canvas publishes the source only after the review returns a valid result. A missing, malformed, or failed review fails the generation job closed.
5. A review with no findings allows the frontend to mount the artifact automatically.
6. A review with findings stops before execution and shows the result. The viewer can inspect the source or run that exact build anyway.
7. Legacy versions without a persisted review also stop before execution.
8. Canvas records a SHA-256 over the complete frozen artifact manifest. A rebuilt or changed artifact has a different hash and requires a new execution decision when gated.

Exact-build execution choices are stored in the browser, partitioned by PostHog user ID. An anonymous viewer can run an exact build for the current browser session. This client-side consent state is a user-experience boundary; server authorization remains the data boundary.

There is intentionally no “trust widgets by this author” option. An author is not the sole authority over a collaborative notebook node: another editor can change its instructions, regenerate it, restore a version, or otherwise replace the artifact after the original author created it. Binding trust to an immutable build is stable; binding it to a mutable ownership label is not.

Same-team scoping reduces exposure but does not eliminate realistic risk. The cases worth guarding against include:

- an editor intentionally adding a deceptive or disruptive widget for teammates;
- a compromised editor account regenerating an existing, previously benign node;
- prompt injection or a generator/supply-chain defect producing behavior nobody intended;
- a future copied or shared notebook carrying active content into a context where the viewer did not create it;
- a notebook changing membership or editorial ownership over time.

The sandboxed cross-origin iframe, Canvas CSP, signed artifact route, capability manifest, and permission-checked dataframe bridge limit blast radius. They do not turn arbitrary JavaScript into trusted code. Runtime navigation interception is defense-in-depth for preview reliability, not a security claim. The Navigation API guard applies only in Chromium. Capturing link clicks and form submissions plus disabling `window.open` blocks common paths in other browsers, but it cannot prove arbitrary programmatic self-navigation is impossible.

The automated review is advisory because a model cannot prove arbitrary or obfuscated JavaScript safe. A clean review improves the first-pass decision but does not replace the runtime controls above or provide a security guarantee.
