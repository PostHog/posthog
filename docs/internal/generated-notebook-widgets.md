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
- Generation uses dataframes with completed runs and skips cells that have not run. Each preview load pins permission-checked pages to one run and reads at most 5,000 rows per connected dataframe without sending values to the model. Across all its dataframes, one preview reads at most 200 pages and 32 MiB of response data.
- Improving a notebook widget requires completed results for its existing inputs, including renamed connections, and preserves their slots and schemas. Unrelated cells without completed results are still skipped.
- Notebook-managed Canvas artifacts use a restricted source policy. Signed artifact URLs can render them, but the ordinary Canvas API cannot list or edit them.
- `<Widget>` is the only notebook markdown tag for generated widgets.
- Widget previews allow pointer lock for interactive controls such as games. Both the iframe and artifact CSP permit `allow-pointer-lock`; the preview URL varies to refresh previously cached CSP headers.
- Organizations must approve AI data processing before a job is queued and when its worker starts.
- Every widget endpoint requires the `notebook-generated-widgets` feature flag: creation, status, history, source, restore, cancellation, and dataframe reads. While it is disabled, existing widget nodes still render but every request they make returns 404. A generation job that is already running does not recheck the flag; it finishes model generation and the Canvas build, bounded by the 10-minute stale window and the 15-minute activity timeout. Keep the flag disabled until the generated-code data boundary and mixed-version Canvas rollout are approved.
- Production artifact delivery requires `CANVAS_ARTIFACT_ORIGIN`, a dedicated bare HTTPS origin with no path, query, fragment, or credentials, set before rollout. A production deploy with it unset boots clean, but every widget builds and then reports its preview unavailable, because no artifact URL is minted. Artifact URLs use Django's rotating `SECRET_KEY` values for signing by default. Deployments can set `CANVAS_ARTIFACT_SIGNING_KEYS` for independent rotation.

“Widget” is the umbrella term. Data visualizations are one possible widget type.

## Reusable widgets

The reusable catalog fields, demo data, input bindings, and pending reviews share one schema migration: `notebooks.0022_reusable_widgets`, after `0021_kernelruntime_sandbox_end`.
The four new non-null fields retain database defaults, so workers from before this migration can still create widgets, versions, and placements during a rolling deploy or rollback.
Local databases that already applied the earlier catalog, input-binding, pending-review, and merge migrations need their migration records reconciled after verifying all nine fields exist. Record the consolidated migration as applied and prune the four superseded records in both the development and reused test databases. Preserve the existing tables and data; rolling back those field additions would discard saved catalog metadata, bindings, and demo rows.

The notebooks index shows **Notebooks** and **Reusable widgets** tabs only when `notebook-generated-widgets` is enabled. With the flag disabled, it shows the notebook list without tabs.
Each reusable widget's page header has a back arrow before the notebook icon that returns to the **Reusable widgets** tab.

A generated widget can be published to the project-scoped reusable widget catalog using **Make reusable…** beside its version pin controls. Publishing gives the widget a stable ID, keeps its existing immutable version history, and creates empty demo inputs from the input contract. Publishing preserves the placement’s bindings and does not copy notebook rows or source run identifiers. Authors can add up to 20 invented sample rows per input using **Demo data**. The success message links to the catalog on the notebooks index's **Reusable widgets** tab. Each catalog entry has a dedicated page for its live demo, input contract, source, usage count, and shared improvement or regeneration actions.

Newly generated widgets and reusable placements follow the latest version by default. The version history shows **Following latest version** while this is enabled. Choosing **Pin this version** adds a `version="…"` attribute to the notebook's Markdown, including for private widgets. **Follow latest version** removes that attribute and the pin. Generating or restoring a private version preserves whether the placement follows latest or is pinned. Shared source changes must be made from the catalog page; **Fork and edit here** copies the selected version into a private notebook widget that follows latest before enabling notebook-local changes.

Improving or regenerating a reusable widget creates a draft instead of changing the published version. Review the draft's runnable demo, input contract, security review, and source on the catalog detail page. Draft builds preserve any queued build for the published source. Clean drafts without dataframe access render automatically; **Save version** still publishes them for unpinned placements, while **Discard draft** leaves the published version unchanged. Discarding cancels draft builds and queues cleanup of their source, artifacts, and database rows. Cleanup retains shared source objects and retries storage failures; the daily retention sweep requeues unfinished cleanup.

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
Incomplete column selections keep attachment disabled, including when opening the advanced editor.
Bindings store only the dataframe name and optional Hog source. The server validates Hog when attaching a widget; the browser compiles and caches it by source text for execution. Client-supplied bytecode is ignored and never saved or executed.
Hog mappings use conversion functions such as `toInt`; SQL casts (`::` and `try_cast`) are rejected during compilation.

Notebook AI treats the document as MDX and writes live component tags outside code fences.
Inline AI receives a bounded, project-scoped catalog of saved widget metadata and input schemas, without saved demo rows or generated source.
The catalog follows the generated-widgets feature flag independently of SQL V2.
A new `<Widget id="…" inputs={{…}} />` in an editable notebook attaches that catalog widget after saving the notebook.
Widgets without inputs also attach when the `inputs` attribute is omitted.
Attachment requests time out after 30 seconds and are canceled when the widget unmounts.
The server remains authoritative for existing placements. The inline response handler also unwraps complete enabled component tags accidentally fenced as unlabeled, Markdown, MDX, or JSX code; disabled tags and other code examples stay fenced.

Catalog pages resume polling an active update when reopened, including during source generation. Failed or canceled updates preserve the change prompt and report the failure even when the published preview still works. Status follows the shared widget's job; generation can use another live placement after the original block is removed.
Publishing a legacy widget reads only schema metadata to fill in its input columns. AI catalog context requires the same resource-level notebook viewer permission as the catalog API.
Prepared Canvas source uploads are removed if generation is abandoned or the notebook transaction rolls back. Committed versions retain their source objects; failed storage cleanup is retried in a background task.
The first prepared draft for a legacy Canvas keeps the original source as its parent version without moving the live head. Promoting the draft preserves that history for restoration.
Pinning the displayed version keeps its preview available. Updated input bindings refresh the preview, including bindings changed through **Match with AI**. Failed Hog compilation can be retried without reloading the page.
Fork requests accept an optional `version_id`, so forking copies the version selected in history. Omitting it copies the placement's pinned or latest version. Concurrent attachments to the same node reuse one placement.
Fork publication and placement replacement commit together. If either fails, both roll back and the build is not queued.

Reusable widgets remain behind the `notebook-generated-widgets` feature flag and preserve the generated-code trust gate described below. Catalog access requires resource-level notebook permissions, rather than an access grant to one notebook. Reading or editing demo rows also requires query viewer access and the `query:read` token scope. Demo inputs start empty. Authors must use invented sample rows because saved demos are shared with catalog viewers and do not carry notebook or source access restrictions. Catalog demo approval applies only to the open preview and never grants consent to run the build against notebook data. Editing the demo or switching versions clears this approval.

## Agent access

New widgets default to Claude Sonnet 5. An explicitly selected model stays selected.
Widget IDs are saved when their settings, title, or panel visibility change, so editing a widget keeps its generation history attached.

New SQL cells receive a unique name beginning with `sql_df_`; Python cells receive one beginning with `df_`.
You can rename a dataframe in its result panel.
The SQL and insight dataframe name rows are visible when either `revamped-py-notebooks` or `notebook-generated-widgets` is enabled.
The widget flag enables HogQL dataframe preparation. Python, kernel-backed SQL, and direct connections require `revamped-py-notebooks`.
Insights that expose SQL have the same dataframe name field below their results, starting with `insight_df` (with a numeric suffix when needed).
An editor prepares the insight's dataframe when a SQL or Python cell first references it, before generating a widget, or when rerunning a widget's data dependencies.
Widget generation continues with the available dataframes if an embedded insight cannot be prepared.
Refreshing a widget prepares only its connected insight dataframes; SQL and Python cells prepare any insights they reference when they run.
An insight preparation failure still stops a cell or widget refresh that depends on that insight.
Widgets that use only insight dataframes refresh after preparation without requiring a SQL or Python cell.
Opening a notebook, renaming a dataframe, or refreshing an insight's display does not prepare dataframes or save preparation metadata.
Preparation uses the insight query cache and saves the run reference and column metadata only after the SQL run completes.
If the insight query changes during preparation, the completed result is discarded and the editor can try again.
Concurrent preparation requests from the same user reuse the same matching run for up to one hour.
Run reuse is disabled for token-only callers because runs do not record their individual identities.
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
**Ask AI** is disabled until the organization approves AI data processing, including submission from saved prompt blocks.
Inline notebook artifacts update the open notebook without saving a second copy, even when the tool requests a save.
Full-notebook replacements preserve the retained question when **Keep question with answer** is on.
Standalone AI notebook saves preserve Markdown separators and live MDX cells, including `<SQLV2 />` and `<Widget />`, while resolving visualization references.
Its notebook context and `create_notebook` tool share the same instructions for inserting `<Widget title="Interactive visualization" prompt="Describe the visualization" />`.
When the widget flag is enabled, inline AI insertion also converts plain, `md`, or `markdown` code fences containing only valid `<Widget>` tags into widget blocks. Fences containing other code, malformed tags, or an explicit language such as `text` remain code examples.
The user clicks **Generate widget** in the inserted block's settings to start generation.
The widget flag and SQL/Python cell flag are independent; enabling widgets does not grant access to SQLV2 or PythonV2 cells.

The MCP tools `notebooks-widget-generate`, `notebooks-widget-status`, and `notebooks-widget-cancel` use the same `notebook-generated-widgets` flag as the editor.
The MCP server evaluates this flag for the authenticated user when it resolves available tools.
Generation also requires the organization's AI data processing consent and the `notebook:write` and `query:read` scopes.

An agent inserts a `Widget` component through `notebooks-add-cell`, then calls `notebooks-widget-generate` with its returned `node_id`.
Markdown editing can also insert `<Widget nodeId="widget-example" prompt="Show an interactive chart" />` into a saved notebook.
Only notebook SQL and Python dataframes with completed runs are available to generation; unrun cells do not block it.
Inserting the tag does not start a generation job.
The agent polls status and directs the user to the notebook for review and execution consent.
MCP responses for widget generation, status, and attachment omit the preview URL so previews open through the notebook's existing consent flow.
These responses wrap status, errors, and security findings as untrusted reference data, with instructions for agents to treat the content as data rather than commands.

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

Ordinary `<Embed>` blocks accept absolute HTTP or HTTPS URLs.
Public sharing removes invalid embed sources before serving notebook markdown.
Embed frames run without same-origin access, including when an external URL redirects to the application origin.
Embedded pages that require cookies or browser storage may need to be opened directly.

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

## Usage instrumentation

The backend emits `reusable widget operation` after a successful database commit for publish, attach, fork, save version, discard, restore, demo data edits, and accepted generation jobs.
The `operation` values are `publish`, `attach`, `fork`, `save_version`, `discard`, `restore`, `demo_data_update`, and `generate`.
Generation events describe accepted jobs, not completed builds; retries with the same generation ID do not emit another event.

Events include widget and version IDs, placement notebook and node IDs where applicable, `is_rebind`, and `bindings_use_hog`.
Forks include `source_widget_id` and the source version in `previous_version_id`; saved and restored versions include the previous published version.
Generation events include `generation_id` and `generation_operation`.
Telemetry excludes widget names, prompts, source, demo rows, dataframe names, and Hog programs.

`origin` uses the shared request-source classifier: browser sessions map to `ui`, ordinary API tokens to `api`, and MCP requests to `mcp` or the recognized agent surface.
In-process callers default to `server` and can pass their own origin.
The frontend marks attachment while loading an existing MDX widget with `X-PostHog-Widget-Auto-Attach: true`, which produces `origin=auto_attach`.
This distinguishes automatic attachment from deliberate UI attachment but does not identify who originally wrote the MDX tag.
The origin and automatic-attachment header are analytics metadata, not authorization signals.

Shared catalog changes also create `GeneratedWidget` activity-log entries for publish, save version, discard, restore, and demo data edits.
These entries retain the actor, widget name, operation, version IDs, and changed field, including the ID of a discarded draft after its row is deleted.
Demo data values are excluded from the audit trail.
Both audit entries and analytics callbacks are dropped if the surrounding transaction rolls back.

Autocapture can identify the publish and picker confirmation buttons with `reusable-widget-publish` and `reusable-widget-attach`.
