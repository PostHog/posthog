# Generated notebook widgets

Notebooks can generate interactive widgets from instructions and the notebook's SQL and Python dataframe context.

- Generation runs as a durable background job. The notebook shows its phase, elapsed time, cancellation, and terminal errors. Queued jobs stop immediately when canceled.
- Failed jobs expose a stable error code and the failed source-generation, security-review, or publishing phase. AI request logs include upstream status and request IDs when available.
- Source generation and security review send Claude requests through the native Anthropic Messages format in both local and cloud environments.
- On the Go AI gateway, each job authenticates both model calls with a temporary Redis-only `llm_gateway:read` project credential. The gateway attributes and bills the calls to that project. The worker clears the credential before publishing, on failure, or when a stale job is reconciled.
- Successful source, generated titles, prompts, models, dataframe contracts, and security reviews are stored as immutable versions.
- People can inspect history and source, request source changes, restore an earlier version, improve the current widget, or regenerate it.
- A new widget uses “Create an interactive visualization of the data in this notebook” when its instruction field is left empty.
- Running a widget re-runs only its connected SQL and Python data cells in dependency order. It reloads the existing preview without generating a new version.
- A fast model reviews the exact generated source before Canvas publishes it. A review failure stops publication.
- Every preview stops at a gate that shows the automated review result and links to the source. The viewer must choose to run the exact build.
- Every ready build exposes the SHA-256 of its frozen Canvas artifact manifest. “Run widget” records consent for that exact hash. A later build with different artifact contents requires a new decision. A build whose manifest is byte-identical, such as an identical rebuild, reuses the earlier consent.
- “View source” remains available before a widget runs and reads the source belonging to the selected historical version.
- Every dataframe must have a completed run before generation. Each preview load pins permission-checked pages to one run and reads at most 5,000 rows per connected dataframe without sending values to the model. Across all its dataframes, one preview reads at most 200 pages and 32 MiB of response data.
- Notebook-managed Canvas artifacts use a restricted source policy. Signed artifact URLs can render them, but the ordinary Canvas API cannot list or edit them.
- `<Widget>` is the only notebook markdown tag for generated widgets.
- Organizations must approve AI data processing before a job is queued and when its worker starts.
- Every widget endpoint requires the `notebook-generated-widgets` feature flag: creation, status, history, source, restore, cancellation, and dataframe reads. While it is disabled, existing widget nodes still render but every request they make returns 404. A generation job that is already running does not recheck the flag; it finishes model generation and the Canvas build, bounded by the 10-minute stale window and the 15-minute activity timeout. Keep the flag disabled until the generated-code data boundary and mixed-version Canvas rollout are approved.
- Production artifact delivery requires `CANVAS_ARTIFACT_ORIGIN`, a dedicated bare HTTPS origin with no path, query, fragment, or credentials, set before rollout. A production deploy with it unset boots clean, but every widget builds and then reports its preview unavailable, because no artifact URL is minted. Artifact URLs use Django's rotating `SECRET_KEY` values for signing by default. Deployments can set `CANVAS_ARTIFACT_SIGNING_KEYS` for independent rotation.

“Widget” is the umbrella term. Data visualizations are one possible widget type.

## Generated-code trust model

Generated widget source is arbitrary React and JavaScript. It is not a restricted widget schema, and PostHog does not claim to make it safe by parsing an AST, matching source text, or blocking selected syntax. JavaScript can construct equivalent behavior dynamically, so source-shape validation would create a false security boundary while breaking legitimate widgets.

The generated-code trust flow works as follows:

1. Existing static validation rejects unsupported imports, direct network APIs, dynamic imports, inline scripts, and undeclared dataframe reads.
2. A fast model reviews the validated source as untrusted input. It looks for concrete exfiltration, deception, dynamic execution, browser access, side effects, and resource-abuse risks that static checks cannot reliably identify.
3. The immutable widget version stores the highest severity, summary, findings, review model, review-instruction version, and review time. Restoring a version carries forward the review of that exact source.
4. Canvas publishes the source only after the review returns a valid result. A missing, malformed, or failed review fails the generation job closed.
5. Every reviewed build stops before execution and shows the result. The viewer can inspect the source before choosing to run that exact build.
6. A review with findings changes the gate warning and requires the viewer to run the widget anyway.
7. Legacy versions without a persisted review also stop before execution.
8. Canvas records a SHA-256 over the complete frozen artifact manifest. The hash covers artifact contents only, with no build or version id, so a build with different contents has a different hash and requires a new execution decision when gated. A build with identical contents keeps the same hash and reuses the earlier decision.

Exact-build execution choices are stored in the browser, partitioned by PostHog user ID. Generated widgets are not rendered in publicly shared notebooks. This client-side consent state is a user-experience boundary; server authorization remains the data boundary.

There is intentionally no “trust widgets by this author” option. An author is not the sole authority over a collaborative notebook node: another editor can change its instructions, regenerate it, restore a version, or otherwise replace the artifact after the original author created it. Binding trust to an immutable build is stable; binding it to a mutable ownership label is not.

Same-team scoping reduces exposure but does not eliminate realistic risk. The cases worth guarding against include:

- an editor intentionally adding a deceptive or disruptive widget for teammates;
- a compromised editor account regenerating an existing, previously benign node;
- prompt injection or a generator/supply-chain defect producing behavior nobody intended;
- a future copied or shared notebook carrying active content into a context where the viewer did not create it;
- a notebook changing membership or editorial ownership over time.

The sandboxed cross-origin iframe, Canvas CSP, signed artifact route, capability manifest, and permission-checked dataframe bridge limit blast radius. They do not turn arbitrary JavaScript into trusted code. Runtime navigation interception is defense-in-depth for preview reliability, not a security claim. The Navigation API guard applies only in Chromium. Capturing link clicks and form submissions plus disabling `window.open` blocks common paths in other browsers, but it cannot prove arbitrary programmatic self-navigation is impossible.

The automated review is advisory because a model cannot prove arbitrary or obfuscated JavaScript safe. A clean review improves the first-pass decision but does not replace the runtime controls above or provide a security guarantee.
