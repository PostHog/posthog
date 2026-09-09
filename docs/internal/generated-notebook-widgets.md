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
- A preview without dataframe inputs runs immediately when its automated review found no potential issues. Previews with dataframe access, flagged reviews, and legacy unreviewed versions require exact-build consent at a gate that links to the source.
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

## Reusable widgets

The reusable catalog fields, demo data, input bindings, and pending reviews share one schema migration: `notebooks.0020_reusable_widgets`, after `0019_squash_2026_09_07_schema_addons`.
Local databases that already applied the earlier catalog, input-binding, pending-review, and merge migrations need their migration records reconciled after verifying all nine fields exist. Record the consolidated migration as applied and prune the four superseded records in both the development and reused test databases. Preserve the existing tables and data; rolling back those field additions would discard saved catalog metadata, bindings, and demo rows.

The notebooks index shows **Notebooks** and **Reusable widgets** tabs only when `notebook-generated-widgets` is enabled. With the flag disabled, it shows the notebook list without tabs.
Each reusable widget's page header has a back arrow before the notebook icon that returns to the **Reusable widgets** tab.

A generated widget can be published to the project-scoped reusable widget catalog using **Make reusable…** beside its version pin controls. Publishing gives the widget a stable ID, keeps its existing immutable version history, and saves up to 20 rows per input as a bounded demo fixture. Capture applies each input’s Hog mapping before saving contract-shaped rows and preserves the publishing placement’s bindings. The success message links to the catalog on the notebooks index's **Reusable widgets** tab. Each catalog entry has a dedicated page for its live demo, input contract, source, usage count, and shared improvement or regeneration actions.

Newly generated widgets and reusable placements follow the latest version by default. The version history shows **Following latest version** while this is enabled. Choosing **Pin this version** adds a `version="…"` attribute to the notebook's Markdown, including for private widgets. **Follow latest version** removes that attribute and the pin. Generating or restoring a private version preserves whether the placement follows latest or is pinned. Shared source changes must be made from the catalog page; **Fork and edit here** copies the selected version into a private notebook widget that follows latest before enabling notebook-local changes.

Improving or regenerating a reusable widget creates a draft instead of changing the published version. Review the draft's runnable demo, input contract, security review, and source on the catalog detail page. Clean drafts without dataframe access render automatically; **Save version** still publishes them for unpinned placements, while **Discard draft** leaves the published version unchanged. Discarding cancels draft builds and queues cleanup of their source, artifacts, and database rows. Cleanup retains shared source objects and retries storage failures; the daily retention sweep requeues unfinished cleanup.

The version dropdown above the preview includes the draft, latest published version, and paginated older versions. Selecting a version switches its preview, input contract, review, demo data, and **View source** together. An older version's **Make latest** action creates a new version from its source, input contract, saved demo data, model, and review. Existing history and notebook pins stay intact. Finish or discard an in-progress update before restoring an older version; stale restore requests are rejected.

**Demo data**, beside **View source**, opens the selected version's saved input rows as a table. Select an input and choose **Edit demo data** to replace its sample using a JSON array of row objects. Each row must keep the input contract's column names; samples are limited to 20 rows per input and 512 KB across all inputs. Saving refreshes the preview immediately. Demo samples are editable preview metadata for the latest version and its draft, without creating a source version or changing notebook data, bindings, or input contracts. Older versions' samples are read-only. Switching inputs requires saving or canceling edits; closing with unsaved edits asks before discarding them.

On wide detail pages, the controls sit beside the preview in a one-third/two-thirds layout. Narrow pages stack them. Drag the preview's bottom-right corner to increase its height. Choose a **Model** in the update form for either **Improve** or **Regenerate**; it defaults to the published version's model. Both actions share an update lock; only the selected action shows a spinner while the other action and model selector are disabled.

`<Widget>` nodes use a stable notebook `nodeId` and an optional `version`. Reusable placements also store the catalog `id` and notebook-local `inputs`. The server remains the source of truth for the placement and its bindings. A binding maps each logical contract slot to a local SQL or Python dataframe, so two instances of the same reusable widget can use different notebook data.

An input binding can also include a pure Hog transform. It receives `rows` as a list of row objects, `columns`, and `frame`, and must return a list of row objects matching the widget's expected contract. Hog is compiled through the existing compiler and runs in the browser VM with no callable functions, no asynchronous steps, a 100 ms timeout, and a 16 MiB memory limit. Direct bindings retain the existing schema-hash check; transformed bindings are validated as bounded tabular output before the iframe receives them.
Every mapped row must include all declared columns. Only those columns reach the widget, in contract order; extra fields are discarded, and empty pages retain the contract's columns.

The notebook MCP surface exposes catalog list, detail, and attach operations. Agents should search saved widgets before generating a new visualization, inspect the candidate's contract, and provide explicit `{ source, hog? }` bindings when attaching it.

The input picker connects matching schemas by selecting a dataframe, even when its name differs from the widget's logical input.
For mismatched schemas, it lists missing columns and type differences and offers source-column selectors, **Match with AI**, or **Advanced mapping**.
Column selectors produce a quoted Hog projection; conversions and calculations use AI or the advanced editor, which includes variable descriptions and an example.
**Match with AI** opens the AI side panel with the current selection for the user to send. The agent inspects the notebook and saved contract and attaches the selected widget to the existing node.
Changing the selected dataframe clears its previous mapping.

Notebook AI treats the document as MDX and writes live component tags outside code fences.
Inline AI receives a bounded, project-scoped catalog of saved widget metadata and input schemas, without saved demo rows or generated source.
A new `<Widget id="…" inputs={{…}} />` in an editable notebook attaches that catalog widget after saving the notebook.
The server remains authoritative for existing placements. The inline response handler also unwraps complete enabled component tags accidentally fenced as unlabeled, Markdown, MDX, or JSX code; disabled tags and other code examples stay fenced.

Reusable widgets remain behind the `notebook-generated-widgets` feature flag and preserve the generated-code trust gate described below. Catalog access requires resource-level notebook permissions, rather than an access grant to one notebook. Reading or editing demo rows also requires query viewer access and the `query:read` token scope. Publishing demo data copies project data into another team-scoped model, so the publishing dialog makes that behavior explicit.

## Agent access

New notebooks place the typing caret in the title, including when opened through the command menu. Enter continues into the notebook body.
The notebook's inline **Ask AI** uses LangGraph and receives widget authoring instructions when `notebook-generated-widgets` is enabled for the user.
The bookmark toggle **Keep question with answer** is on by default, retaining the question and the submitting user's name above the answer. Turning it off saves `keepQuestion={false}` on that prompt.
Its notebook context and `create_notebook` tool share the same instructions for inserting `<Widget title="Interactive visualization" prompt="Describe the visualization" />`.
When the widget flag is enabled, inline AI insertion also converts plain, `md`, or `markdown` code fences containing only valid `<Widget>` tags into widget blocks. Fences containing other code, malformed tags, or an explicit language such as `text` remain code examples.
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

In notebooks, the widget title's **More actions** (`…`) menu contains **Open reusable widget**, **View source**, the automated review result, and the selected build identifier. Running widgets show their preview without a source and review toolbar. Widgets that require approval still show the review gate before running.

Generated widget source is arbitrary React and JavaScript. It is not a restricted widget schema, and PostHog does not claim to make it safe by parsing an AST, matching source text, or blocking selected syntax. JavaScript can construct equivalent behavior dynamically, so source-shape validation would create a false security boundary while breaking legitimate widgets.

The generated-code trust flow works as follows:

1. Existing static validation rejects unsupported imports, direct network APIs, dynamic imports, inline scripts, and undeclared dataframe reads.
2. A fast model reviews the validated source as untrusted input. It looks for concrete exfiltration, deception, dynamic execution, browser access, side effects, and resource-abuse risks that static checks cannot reliably identify.
3. The immutable widget version stores the highest severity, summary, findings, review model, review-instruction version, and review time. Restoring a version carries forward the review of that exact source.
4. Canvas publishes the source only after the review returns a valid result. A missing, malformed, or failed review fails the generation job closed.
5. A build whose review found no potential issues runs immediately only when it has no dataframe access. In notebooks, the review result remains available in the title menu.
6. Builds with dataframe access, reviews with findings, and legacy versions without a persisted review stop before execution and require exact-build consent.
7. Canvas records a SHA-256 over the complete frozen artifact manifest. The hash covers artifact contents only, with no build or version id, so a build with different contents has a different hash and requires a new execution decision when gated. A build with identical contents keeps the same hash and reuses the earlier decision.

Exact-build execution choices are stored in the browser, partitioned by PostHog user ID. Generated widgets are not rendered in publicly shared notebooks. This client-side consent state is a user-experience boundary; server authorization remains the data boundary.

After consent, the bridge exposes only the version’s declared dataframes through permission-checked endpoints. The Canvas CSP keeps `connect-src 'none'`, but iframe self-navigation can still transmit data. A clean automated review cannot prove arbitrary JavaScript safe, so dataframe access requires consent even when no findings were reported.

There is intentionally no “trust widgets by this author” option. An author is not the sole authority over a collaborative notebook node: another editor can change its instructions, regenerate it, restore a version, or otherwise replace the artifact after the original author created it. Binding trust to an immutable build is stable; binding it to a mutable ownership label is not.

Same-team scoping reduces exposure but does not eliminate realistic risk. The cases worth guarding against include:

- an editor intentionally adding a deceptive or disruptive widget for teammates;
- a compromised editor account regenerating an existing, previously benign node;
- prompt injection or a generator/supply-chain defect producing behavior nobody intended;
- a future copied or shared notebook carrying active content into a context where the viewer did not create it;
- a notebook changing membership or editorial ownership over time.

The sandboxed cross-origin iframe, Canvas CSP, signed artifact route, capability manifest, and permission-checked dataframe bridge limit blast radius. They do not turn arbitrary JavaScript into trusted code. Runtime navigation interception is defense-in-depth for preview reliability, not a security claim. The Navigation API guard applies only in Chromium. Capturing link clicks and form submissions plus disabling `window.open` blocks common paths in other browsers, but it cannot prove arbitrary programmatic self-navigation is impossible.

The automated review is advisory because a model cannot prove arbitrary or obfuscated JavaScript safe. A clean review improves the first-pass decision but does not replace the runtime controls above or provide a security guarantee.
