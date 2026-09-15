# Generated notebook widgets

Notebooks can generate interactive widgets from instructions and the notebook's SQL and Python dataframe context.

- Generation runs as a durable background job. The notebook shows its phase, elapsed time, cancellation, and terminal errors. Queued jobs stop immediately when canceled.
- Failed jobs expose a stable error code and the failed source-generation, security-review, or publishing phase. AI request logs include upstream status and request IDs when available.
- Source generation and security review send Claude requests through the native Anthropic Messages format in both local and cloud environments.
- Successful source, generated titles, prompts, models, dataframe contracts, and security reviews are stored as immutable versions.
- People can inspect history and source, request source changes, restore an earlier version, improve the current widget, or regenerate it.
- A new widget uses “Create an interactive visualization of the data in this notebook” when its instruction field is left empty.
- Running a widget re-runs only its connected SQL and Python data cells in dependency order. It reloads the existing preview without generating a new version.
- A fast model reviews the exact generated source before Canvas publishes it. A review failure stops publication.
- A preview runs immediately only when its automated review found no potential issues and its immutable version exposes no notebook dataframes. Every dataframe-bearing, flagged, or legacy unreviewed version stops at a gate that shows the result and links to the source.
- Every ready build exposes the SHA-256 of its frozen Canvas artifact manifest. Choosing “Run widget” at a gate records consent for that exact hash. A later gated build with different artifact contents requires a new decision. A build with identical contents reuses the earlier consent.
- “View source” remains available before a widget runs and reads the source belonging to the selected historical version.
- Every dataframe must have a completed run before generation. Each preview load pins permission-checked pages to one run and reads at most 5,000 rows per connected dataframe without sending values to the model. Across all its dataframes, one preview reads at most 200 pages and 32 MiB of response data.
- Notebook-managed Canvas artifacts use a restricted source policy. Signed artifact URLs can render them, but the ordinary Canvas API cannot list or edit them.
- `<Widget>` is the only notebook markdown tag for generated widgets.
- Widget previews allow pointer lock for interactive controls such as games. Both the iframe and artifact CSP permit `allow-pointer-lock`; the preview URL varies to refresh previously cached CSP headers.
- Organizations must approve AI data processing before a job is queued and when its worker starts.
- Every widget endpoint requires the `notebook-generated-widgets` feature flag: creation, status, history, source, restore, cancellation, and dataframe reads. While it is disabled, existing widget nodes still render but every request they make returns 404. A generation job that is already running does not recheck the flag; it finishes model generation and the Canvas build, bounded by the 10-minute stale window and the 15-minute activity timeout. Keep the flag disabled until the generated-code data boundary and mixed-version Canvas rollout are approved.
- Production artifact delivery requires `CANVAS_ARTIFACT_ORIGIN`, a dedicated bare HTTPS origin with no path, query, fragment, or credentials, set before rollout. A production deploy with it unset boots clean, but every widget builds and then reports its preview unavailable, because no artifact URL is minted. Artifact URLs use Django's rotating `SECRET_KEY` values for signing by default. Deployments can set `CANVAS_ARTIFACT_SIGNING_KEYS` for independent rotation.

“Widget” is the umbrella term. Data visualizations are one possible widget type.

## Agent access

New widgets default to Claude Sonnet 5. An explicitly selected model stays selected.
Widget IDs are saved when their settings, title, or panel visibility change, so editing a widget keeps its generation history attached.

New SQL cells receive a unique name beginning with `sql_df_`; Python cells receive one beginning with `df_`.
You can rename a dataframe in its result panel.
The SQL and insight dataframe name rows are visible when either `revamped-py-notebooks` or `notebook-generated-widgets` is enabled.
The widget flag enables HogQL dataframe preparation. Python, kernel-backed SQL, and direct connections require `revamped-py-notebooks`.
Insights that expose SQL have the same dataframe name field below their results, starting with `insight_df` (with a numeric suffix when needed).
An editor prepares the insight's dataframe when a SQL or Python cell first references it, before generating a widget, or when rerunning a widget's data dependencies.
Widgets that use only insight dataframes refresh after preparation without requiring a SQL or Python cell.
Opening a notebook, renaming a dataframe, or refreshing an insight's display does not prepare dataframes or save preparation metadata.
Preparation uses the insight query cache and saves the run reference and column metadata only after the SQL run completes.
If the insight query changes during preparation, the completed result is discarded and the editor can try again.
Concurrent preparation requests reuse the same matching run; completed runs can be reused across editors for one hour.
An unchanged insight with a saved completed run reuses that snapshot. **Refresh dataframe** prepares a fresh snapshot; **Try again** retries a failed preparation.
Viewers and shared notebooks do not show insight dataframe controls or prepare dataframes.

SQL and Python cells save their run ID, column metadata, and row count in the notebook.
A bounded preview keeps at most five rows within 8 KiB and up to 2,048 characters per console stream in the notebook, including runs created through MCP.
The preview helper is shared with MCP, so the MCP TypeScript CI filter covers `products/notebooks/**`.
Full results and images load from the saved run. Older browser tabs can still display the small preview.
Saved result reads remain available if the execution flags are disabled, subject to notebook and query permissions.
Loading a saved result does not execute a cell or mark dependent cells stale. If a saved run is unavailable, the preview stays visible and the cell offers a rerun.

New notebooks place the typing caret in the title, including when opened through the command menu. Enter continues into the notebook body.
The notebook's inline **Ask AI** uses LangGraph and receives widget authoring instructions when `notebook-generated-widgets` is enabled for the user.
The bookmark toggle **Keep question with answer** is on by default, retaining the question and the submitting user's name above the answer. Turning it off saves `keepQuestion={false}` on that prompt.
Its notebook context and `create_notebook` tool share the same instructions for inserting `<Widget title="Interactive visualization" prompt="Describe the visualization" />`.
Inline AI insertion also converts plain, `md`, or `markdown` code fences containing only valid `<Widget>` tags into widget blocks. Fences containing other code, malformed tags, or an explicit language such as `text` remain code examples.
The user clicks **Generate widget** in the inserted block's settings to start generation.
The widget flag and SQL/Python cell flag are independent; enabling widgets does not grant access to SQLV2 or PythonV2 cells.

The MCP tools `notebooks-widget-generate`, `notebooks-widget-status`, and `notebooks-widget-cancel` use the same `notebook-generated-widgets` flag as the editor.
The MCP server evaluates this flag for the authenticated user when it resolves available tools.
Generation also requires the organization's AI data processing consent and the `notebook:write` and `query:read` scopes.

An agent inserts a `Widget` component through `notebooks-add-cell`, then calls `notebooks-widget-generate` with its returned `node_id`.
Markdown editing can also insert `<Widget nodeId="widget-example" prompt="Show an interactive chart" />` into a saved notebook.
All notebook SQL and Python dataframes must have completed runs before generation.
Inserting the tag does not start a generation job.
The agent polls status and directs the user to the notebook for review and execution consent.
MCP responses omit the preview URL so previews open through the notebook's existing consent flow.

## Generated-code trust model

Generated widget source is arbitrary React and JavaScript. It is not a restricted widget schema, and PostHog does not claim to make it safe by parsing an AST, matching source text, or blocking selected syntax. JavaScript can construct equivalent behavior dynamically, so source-shape validation would create a false security boundary while breaking legitimate widgets.

The generated-code trust flow works as follows:

1. Existing static validation rejects unsupported imports, direct network APIs, dynamic imports, inline scripts, and undeclared dataframe reads.
2. A fast model reviews the validated source as untrusted input. It looks for concrete exfiltration, deception, dynamic execution, browser access, side effects, and resource-abuse risks that static checks cannot reliably identify.
3. The immutable widget version stores the highest severity, summary, findings, review model, review-instruction version, and review time. Restoring a version carries forward the review of that exact source.
4. Canvas publishes the source only after the review returns a valid result. A missing, malformed, or failed review fails the generation job closed.
5. A build whose review found no potential issues runs immediately only when its immutable dataframe allow-list is empty. The review result stays visible above the preview.
6. Every build with notebook dataframe access stops before execution and requires exact-build consent, even when its review is green.
7. Reviews with findings and legacy versions without a persisted review also stop before execution.
8. Canvas records a SHA-256 over the complete frozen artifact manifest. The hash covers artifact contents only, with no build or version id, so a build with different contents has a different hash and requires a new execution decision when gated. A build with identical contents keeps the same hash and reuses the earlier decision.

Exact-build execution choices are stored in the browser, partitioned by PostHog user ID. Generated widgets are not rendered in publicly shared notebooks. This client-side consent state is a user-experience boundary; server authorization remains the data boundary.

The automatic path requires an empty dataframe allow-list, exposes no PostHog capability, and grants no network origin. The Canvas CSP keeps `connect-src 'none'`. A green automated verdict never substitutes for viewer consent when generated code can access notebook data.

There is intentionally no “trust widgets by this author” option. An author is not the sole authority over a collaborative notebook node: another editor can change its instructions, regenerate it, restore a version, or otherwise replace the artifact after the original author created it. Binding trust to an immutable build is stable; binding it to a mutable ownership label is not.

Same-team scoping reduces exposure but does not eliminate realistic risk. The cases worth guarding against include:

- an editor intentionally adding a deceptive or disruptive widget for teammates;
- a compromised editor account regenerating an existing, previously benign node;
- prompt injection or a generator/supply-chain defect producing behavior nobody intended;
- a future copied or shared notebook carrying active content into a context where the viewer did not create it;
- a notebook changing membership or editorial ownership over time.

The sandboxed cross-origin iframe, Canvas CSP, signed artifact route, capability manifest, and permission-checked dataframe bridge limit blast radius. They do not turn arbitrary JavaScript into trusted code. Runtime navigation interception is defense-in-depth for preview reliability, not a security claim. The Navigation API guard applies only in Chromium. Capturing link clicks and form submissions plus disabling `window.open` blocks common paths in other browsers, but it cannot prove arbitrary programmatic self-navigation is impossible.

The automated review is advisory because a model cannot prove arbitrary or obfuscated JavaScript safe. A clean review improves the first-pass decision but does not replace the runtime controls above or provide a security guarantee.
