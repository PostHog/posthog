# Migrating CDP hog function templates from Python to Node

Status: proposed, not started.
Owner: #team-cdp.

Working doc for moving the 52 hog function templates that still live in `posthog/cdp/templates/` over to
`nodejs/src/cdp/templates/`, then deleting the Python side.
Each template moves in its own PR; this doc is the shared recipe and the checklist.

## Why

Templates are defined in two places today, and the Python half is the worse half.

A Python template is tested by `BaseHogFunctionTemplateTest`, which compiles the Hog and runs it through the
Python HogVM interpreter with `fetch` stubbed as a `MagicMock`. That is not what runs in production. It cannot
suspend on a fetch and resume with a response, so nothing after the first HTTP call is exercised — including
every error path a destination has.

A Node template is tested by `TemplateTester`, which runs the template through `HogExecutorAsyncService`, the
same executor the cyclotron workers use. Fetches suspend the invocation and resume via `invokeFetchResponse`,
so a test asserts the real outbound request and then drives the response back in. That is the harness we want
every template on.

Consolidating also removes the Python-only concepts that have no Node equivalent and no reason to exist
(`HogFunctionTemplateDC`, `BaseHogFunctionTemplateTest`, the STPyV8 site-destination harness), and leaves one
place to add a template.

## Where we are today

Both sides feed the same Postgres table. Neither serves templates at request time.

```
posthog/cdp/templates/**/template_*.py   nodejs/src/cdp/templates/**/*.template.ts
   (52 HogFunctionTemplateDC)                    (57 HogFunctionTemplate)
              │                                             │
              │                              GET /api/hog_function_templates  (cdp-api.ts)
              │                                             │
              └──────────────┬──────────────────────────────┘
                             ▼
        posthog/management/commands/sync_hog_function_templates.py
           (also pulls 25 warehouse-source webhook templates)
                             │  sync_template_to_db → serializer → model.save()
                             ▼
        posthog_hogfunctiontemplate      ← bytecode compiled here, sha computed here
                             │
                             ├─► PublicHogFunctionTemplateViewSet → frontend
                             └─► HogFunctionTemplateManagerService (Node, at execution time)
```

The sync runs on Django boot via `queue_sync_hog_function_templates` (Redis-locked to once an hour) and as a
Celery task.

Consequences that shape the plan:

- **The DB row is the contract, not the source file.** Nothing imports a template object at request time. A
  template that moves from Python to Node lands in the same table, under the same `template_id`, and every
  existing `HogFunction` keeps resolving. The move is invisible to users if the content is preserved.
- **Bytecode compilation stays in Python either way.** Node ships the `code` string only;
  `HogFunctionTemplate.save()` calls `compile_hog`. Nothing about that changes.
- **`sha` is content-derived**, from `{id, code, code_language, inputs_schema, status, mapping_templates,
  filters, icon_url, masking}`. Change any of those and the sync writes a new row rather than updating.

## Scope

**In:** the 42 Hog destinations and the 10 JavaScript site templates.

**Out:** the 25 `warehouse_source_webhook` templates under
`products/warehouse_sources/backend/temporal/data_imports/sources/*/webhook_template.py`. They are owned by
data warehouse and each one is paired with its Temporal import source through the Python `SourceRegistry`.
Moving them would split a source definition across two languages. `posthog/cdp/templates/hog_function_template.py`
therefore survives this work — those 25 templates import `HogFunctionTemplateDC` from it.

## What must not break

Treat these as the acceptance criteria for every PR in phases 1 and 2.

1. **`template_id` is unchanged.** It is the join key to every existing `HogFunction` row, to `plugin-*`
   migration lookups, and to hardcoded ids in the frontend. A renamed template orphans customer functions.
2. **`code` is byte-identical** unless the PR is explicitly a behavior fix. The UI's "Modified" tag comes from
   `hogFunction.template.code !== configuration.hog` (`hogFunctionConfigurationLogic.tsx`), so any whitespace
   change to the Hog source flags every customer's function as modified.
3. **`inputs_schema` keys, defaults and `secret` flags are unchanged.** Existing functions store inputs keyed
   by these; a renamed key silently drops a configured value. `secret` drives encryption-at-rest and log
   masking in the workflows API.
4. **`status` and `free` are unchanged.** `status` gates catalog visibility; `free` gates plan availability.
5. **`mapping_templates` are preserved**, including `include_by_default` — it decides which mappings are
   pre-checked when someone installs the destination.

A template with no `mapping_templates` (all 42 destinations) that satisfies 1–4 will produce an identical `sha`
and not even write a new DB row.

## Phase 0 — prerequisites

Land these before porting anything.

### 0.1 Normalize `mapping_templates` on ingest

`dataclasses.asdict` emits every unset optional field as an explicit `null`; the Node JSON omits the key.
`HogFunctionMappingTemplateSerializer` declares those fields `required=False, allow_null=True`, so the two
paths produce different `validated_data` and therefore different `sha` for the same logical template:

```
python(asdict) -> {'name': 'Order Completed', 'include_by_default': True, 'use_all_events_by_default': None,
                   'filters': {...}, 'inputs': None, 'inputs_schema': [...]}
node(json)     -> {'name': 'Order Completed', 'include_by_default': True,
                   'filters': {...}, 'inputs_schema': [...]}
```

This is cosmetic — it writes a redundant row, and users see nothing, because `templateHasChanged` compares
`code` rather than `sha`. But it makes "did this port change anything?" unanswerable by diffing shas, which is
the cheapest verification we have. Strip null-valued keys from `mapping_templates` entries in
`sync_template_to_db` so both paths converge, land it alone, and confirm the shas of the four affected
templates settle.

Affects `template-blank-site-destination`, `template-reddit-pixel`, `template-snapchat-pixel`,
`template-tiktok-pixel` — the only in-scope templates carrying `mapping_templates`.

### 0.2 Build a site template harness in Node

Node has the `site_destination` type and one template using it (`google-tag-manager.template.ts`), but
`TemplateTester` has no path for `site_destination` or `site_app` and that template has no test. Ten templates
in phase 2 need this; do not start phase 2 without it.

The Python equivalent, `BaseSiteDestinationFunctionTest`, POSTs a HogFunction to the Django API, transpiles it
via `get_transpiled_function`, and executes the result in STPyV8 against a stub `window`/`document`. Only
`template-reddit-pixel` uses it.

The Node harness needs to reach the same place without the Django round trip. Transpilation lives in Python
(`posthog/cdp/site_functions.py` → `JavaScriptCompiler`), so the options are:

- **(a)** shell out to the Python transpiler the way `compiler.ts` already shells out to `bin/hoge` for Hog,
  then run the output under `jsdom` or `node:vm`. Consistent with the existing pattern; keeps one transpiler.
- **(b)** assert on the template's `onLoad`/`onEvent` exports directly, importing the `code` string into a
  `node:vm` context with a stub `posthog` object, and skip transpilation entirely. Cheaper, but tests less.

Prefer (a). Decide before writing it; the choice sets what phase 2's tests can assert.

### 0.3 Decouple `products/cdp/backend/api/hooks.py` from the Zapier template

`hooks.py:11` does `from posthog.cdp.templates.zapier.template_zapier import template as template_zapier` and
reads `.id`, `.description`, `.icon_url` off it at module load. That import must go before
`template-zapier` can move. Replace with the `template-zapier` string literal plus a DB lookup, or inline the
three constants.

### 0.4 Decide the legacy plugin migrators

Ten templates carry a `HogFunctionTemplateMigrator` subclass that converts an old `PluginConfig` into a
HogFunction. The decision is to **delete them**, which removes:

- `HOG_FUNCTION_MIGRATORS` and the ten migrator classes
- `PluginSerializer.hog_function_migration_available` and the `migrate` action (`products/cdp/backend/api/plugin.py`)
- `hog_function_migration_available` in `frontend/src/types.ts` and its use in
  `frontend/src/scenes/data-pipelines/legacy-plugins/PipelinePluginConfiguration.tsx:136`

This is a user-facing removal: the "migrate to hog function" button disappears for those ten plugin types.

**Gate:** check production for enabled `PluginConfig` rows whose `plugin.url` matches any of the ten migrator
`plugin_url` values. If the count is non-trivial, migrate them first, or defer 0.4 to phase 3 and keep the
migrators alive on a DB-backed lookup in the meantime.

The ten: customerio, sendgrid, google_pubsub, google_cloud_storage, engage, posthog, hubspot, rudderstack,
loops, avo. `salesforce` also defines a migrator class (`TemplatSalesforceMigrator`) but it is not registered in
`HOG_FUNCTION_MIGRATORS` and is already dead — delete it with the rest.

This is independent of `posthog/cdp/migrations.py` and `posthog/cdp/legacy_plugins.py`, which resolve
`plugin-{id}` templates from the DB (sourced from Node's `legacy-plugins`). Those stay.

### 0.5 Add a parity check

A test that fails when a `template_id` is defined on both sides, so a half-finished port cannot merge. Cheapest
version: assert the Python id set and the Node id set are disjoint. There are no duplicates today.

## Phase 1 — the 42 Hog destinations

One template per PR, in the order in the checklist below. The recipe is mechanical; the judgement is in the
tests.

### Recipe

Two scripts do the mechanical half. Both read the Python with `ast`, so they run without Django or a database.

```bash
# Generate the Node template from the Python one
python tools/cdp_template_to_ts.py posthog/cdp/templates/slack/template_slack.py

# Prove the ported code is byte-identical (--git reads the Python from a commit you already deleted it in)
python tools/cdp_template_verify.py --git HEAD~1 posthog/cdp/templates/slack/template_slack.py \
    nodejs/src/cdp/templates/_destinations/slack/slack.template.ts
```

Running the Node template tests needs the Hog compiler, which shells out to Python:

```bash
export PATH="$PWD/.venv/bin:$PATH" SECRET_KEY=<any 32+ chars> DEBUG=1
cd nodejs && npx jest src/cdp/templates/_destinations/<vendor>
```

1. **Create the Node template.** `nodejs/src/cdp/templates/_destinations/<vendor>/<slug>.template.ts`, exporting
   `export const template: HogFunctionTemplate = {...}`. Keep the Python vendor directory name — it is already
   snake_case, which matches most of `_destinations/`. Copy `code` verbatim; do not reformat it.

   Three vendor directories already exist on the Node side with a different template in them — `hubspot`,
   `snapchat_ads`, `tiktok_ads`. Add the new file alongside; do not merge the templates.

2. **Register it** in `nodejs/src/cdp/templates/index.ts`: add the import and push it into
   `HOG_FUNCTION_TEMPLATES_DESTINATIONS`.

3. **Port the tests** to `<slug>.template.test.ts` beside the template. This is a rewrite, not a translation —
   the Python assertions were shaped by what `BaseHogFunctionTemplateTest` could see, and the Node harness sees
   more. For each case in the Python test:
   - `run_function(inputs)` → `tester.invoke(inputs, globals)`
   - `get_mock_fetch_calls()` → `expect(response.invocation.queueParameters).toMatchInlineSnapshot()`
   - `self.fetch_responses = {...}` → `tester.invokeFetchResponse(response.invocation, {status, body})`
   - `get_mock_print_calls()` → `response.logs.filter(l => l.level === 'info').map(l => l.message)`

   Then add what Python could not reach: the non-2xx branch, and the resumed-invocation assertion after a
   successful fetch. Most of these templates `throw Error(...)` on `res.status >= 400` and that branch has never
   been tested. Follow `webhook.template.test.ts` and `tiktok.template.test.ts` for the idiom.

   Two harness traps to expect:

   - **Schema defaults containing single quotes do not render.** `compileInputs` in `test/test-helpers.ts`
     compiles each input as `` compileHog(`return f'${value}'`) ``, and an embedded `'` terminates that f-string
     early. Production compiles inputs through `parse_string_template` instead, so the default is fine in
     production and only misrenders under test. Pass the input explicitly rather than snapshotting the broken
     value. `template-slack`'s default `text` hits this.
   - **The Node harness applies `inputs_schema` defaults; the Python one did not.** Bodies will contain fields
     the Python assertions showed as `None`. That is the Node harness being closer to production, not a
     regression — but it means assertions rarely transfer verbatim.
   - `toMatchInlineSnapshot()` cannot be used inside `it.each` (one call site, many snapshots). Assert the value
     directly, which reads better for short strings like error messages anyway.

4. **Delete the Python side**: the `template_*.py`, its `test_*.py`, and the entries in
   `posthog/cdp/templates/__init__.py`. Remove the vendor directory when it is empty.

5. **Verify.** Run the Node tests, then `cdp_template_verify.py` — a byte-identical `code` is the property that
   makes the port invisible to existing functions. Boot the dev stack and run
   `python manage.py sync_hog_function_templates` when you want end-to-end confirmation that the row for that
   `template_id` keeps its `sha`. A changed sha needs an explanation in the PR body.

   Watch for invisible characters. `template-customerio` carried a non-breaking space in its Hog source, which
   only the byte comparison caught. Normalizing it would have flagged every live Customer.io function as
   modified.

### Sequencing

Start with a template that has a migrator and a large test file, so the recipe meets its hardest case early
rather than late. `template-customerio` (240 test LOC, migrator) is a good first one. `template-slack` should
go early too — it is in `TEST_INCLUDE_PYTHON_TEMPLATE_IDS` in the sync command, so moving it exercises the
test-mode allowlist path that the other 41 do not touch.

Leave `template-mailchimp` (deprecated) until last; it may be simpler to delete than to port. Confirm no
enabled HogFunctions reference it first.

## Phase 2 — the 10 JavaScript site templates

Blocked on 0.2. These are `code_language: 'javascript'`, run in the browser via
`posthog/cdp/site_functions.py`'s transpiler, and only one of them (`template-reddit-pixel`) has a test today.

Same recipe, with three differences:

- Target `nodejs/src/cdp/templates/_site/<vendor>/` (new directory) or extend `_destinations/`. Pick one in
  0.2 and stay with it.
- Register in a new `HOG_FUNCTION_TEMPLATES_SITE` list, or in the existing destinations list — `index.ts`
  already carries `google-tag-manager` as a `site_destination` inside
  `HOG_FUNCTION_TEMPLATES_DESTINATIONS`, so extending that is the smaller change.
- Four of these carry `mapping_templates`, so 0.1 must have landed and settled first.

The five `_siteapps` templates (notification bar, pineapple mode, early access features, hogdesk, debug) have
no tests at all. Porting them is a straight code move; write at least a smoke test for each rather than
carrying the gap over.

`template-blank-site-app` and `template-blank-site-destination` are scaffolds shown in the UI as "new
client-side destination". They have no behavior to test beyond compiling.

Once all ten have moved, `posthog/cdp/templates/helpers.py` and the STPyV8 dependency can go.

## Phase 3 — Python teardown

Only after phases 1 and 2 are complete and the parity check shows an empty Python id set.

**Delete:**

- `posthog/cdp/templates/` — every vendor directory, `_siteapps/`, `_internal/`, `helpers.py`,
  `test_cdp_templates.py`
- `HOG_FUNCTION_TEMPLATES` and `HOG_FUNCTION_MIGRATORS` from `posthog/cdp/templates/__init__.py`
- `HogFunctionTemplateMigrator` from `posthog/cdp/templates/hog_function_template.py` (if 0.4 deferred)
- The Python-templates loop and `TEST_INCLUDE_PYTHON_TEMPLATE_IDS` from
  `posthog/management/commands/sync_hog_function_templates.py` — the warehouse-source loop and the Node fetch
  stay, and the warehouse ids move into their own allowlist
- The `STPyV8` dependency from `pyproject.toml`

**Keep** — general hog function machinery, not template-owned:

| File | Why it stays |
| --- | --- |
| `posthog/cdp/templates/hog_function_template.py` | `HogFunctionTemplateDC` + `sync_template_to_db`, used by the 25 warehouse-source webhook templates |
| `posthog/cdp/validation.py` | `compile_hog`, input/filter serializers — used by hog functions, workflows, AI observability |
| `posthog/cdp/filters.py` | filter → HogQL → bytecode, used on live `HogFunction` rows |
| `posthog/cdp/site_functions.py` | transpiles saved HogFunctions; reads the `HogFunction` row, never a template |
| `posthog/cdp/legacy_plugins.py`, `posthog/cdp/migrations.py` | resolve `plugin-*` templates from the DB |
| `products/cdp/backend/models/hog_function_template.py` | the model, the sha, the bytecode compilation |
| `products/cdp/backend/api/hog_function_template.py` | the viewsets the frontend reads |

**Check** that `posthog/test/playwright_setup_functions.py` still seeds the template rows the E2E tests need —
Playwright CI never runs the sync command, so it creates `HogFunctionTemplate` rows directly and will not
notice a template that stopped existing in Python.

## Checklist

`sha?` is ticked when the post-port `sync_hog_function_templates` produces the same sha as before.

### Phase 0

- [ ] 0.1 Normalize `mapping_templates` nulls in `sync_template_to_db`
- [ ] 0.2 Site template harness in Node (decide transpile approach first)
- [ ] 0.3 Decouple `hooks.py` from `template_zapier`
- [ ] 0.4 Production check on the ten migrator plugin URLs, then delete the migrators
- [ ] 0.5 Parity check test (Python and Node id sets disjoint)

### Phase 1 — destinations (42)

| ✓ | sha? | Template | Python source | Status | Test LOC | Migrator |
| --- | --- | --- | --- | --- | --- | --- |
| ☐ | ☐ | `template-customerio` | `customerio/template_customerio.py` | stable | 240 | yes |
| ☐ | ☐ | `template-slack` | `slack/template_slack.py` | stable | 62 | — |
| ☐ | ☐ | `template-activecampaign` | `activecampaign/template_activecampaign.py` | beta | 51 | — |
| ☐ | ☐ | `template-airtable` | `airtable/template_airtable.py` | beta | 61 | — |
| ☐ | ☐ | `template-attio` | `attio/template_attio.py` | beta | 62 | — |
| ☐ | ☐ | `template-avo` | `avo/template_avo.py` | beta | 231 | yes |
| ☐ | ☐ | `template-aws-kinesis` | `aws_kinesis/template_aws_kinesis.py` | beta | 44 | — |
| ☐ | ☐ | `template-braze` | `braze/template_braze.py` | beta | 47 | — |
| ☐ | ☐ | `template-brevo` | `brevo/template_brevo.py` | stable | 41 | — |
| ☐ | ☐ | `template-clearbit` | `clearbit/template_clearbit.py` | beta | 91 | — |
| ☐ | ☐ | `template-discord` | `discord/template_discord.py` | stable | 64 | — |
| ☐ | ☐ | `template-engage-so` | `engage/template_engage.py` | beta | 32 | yes |
| ☐ | ☐ | `template-gleap` | `gleap/template_gleap.py` | beta | 77 | — |
| ☐ | ☐ | `template-google-cloud-storage` | `google_cloud_storage/template_google_cloud_storage.py` | beta | 107 | yes |
| ☐ | ☐ | `template-google-pubsub` | `google_pubsub/template_google_pubsub.py` | beta | 119 | yes |
| ☐ | ☐ | `template-hubspot` | `hubspot/template_hubspot.py` | stable | 443 | yes |
| ☐ | ☐ | `template-hubspot-event` | `hubspot/template_hubspot.py` | stable | ↑ | yes |
| ☐ | ☐ | `template-intercom` | `intercom/template_intercom.py` | stable | 390 | — |
| ☐ | ☐ | `template-intercom-event` | `intercom/template_intercom.py` | stable | ↑ | — |
| ☐ | ☐ | `template-june` | `june/template_june.py` | stable | 330 | — |
| ☐ | ☐ | `template-klaviyo-event` | `klaviyo/template_klaviyo.py` | stable | 197 | — |
| ☐ | ☐ | `template-klaviyo-user` | `klaviyo/template_klaviyo.py` | stable | ↑ | — |
| ☐ | ☐ | `template-knock` | `knock/template_knock.py` | beta | 108 | — |
| ☐ | ☐ | `template-kudosity-sms` | `kudosity/template_kudosity.py` | beta | 117 | — |
| ☐ | ☐ | `template-loops` | `loops/template_loops.py` | stable | 175 | yes |
| ☐ | ☐ | `template-loops-event` | `loops/template_loops.py` | stable | ↑ | yes |
| ☐ | ☐ | `template-mailgun-send-email` | `mailgun/template_mailgun.py` | beta | 103 | — |
| ☐ | ☐ | `template-mailjet-create-contact` | `mailjet/template_mailjet.py` | beta | 50 | — |
| ☐ | ☐ | `template-mailjet-update-contact-list` | `mailjet/template_mailjet.py` | beta | ↑ | — |
| ☐ | ☐ | `template-make` | `make/template_make.py` | stable | 63 | — |
| ☐ | ☐ | `template-meta-ads` | `meta_ads/template_meta_ads.py` | alpha | 169 | — |
| ☐ | ☐ | `template-microsoft-teams` | `microsoft_teams/template_microsoft_teams.py` | stable | 98 | — |
| ☐ | ☐ | `template-onesignal` | `onesignal/template_onesignal.py` | beta | 64 | — |
| ☐ | ☐ | `template-posthog-replicator` | `posthog/template_posthog.py` | stable | 110 | yes |
| ☐ | ☐ | `template-rudderstack` | `rudderstack/template_rudderstack.py` | beta | 133 | yes |
| ☐ | ☐ | `template-salesforce-create` | `salesforce/template_salesforce.py` | beta | 162 | dead |
| ☐ | ☐ | `template-salesforce-update` | `salesforce/template_salesforce.py` | beta | ↑ | dead |
| ☐ | ☐ | `template-sendgrid` | `sendgrid/template_sendgrid.py` | beta | 180 | yes |
| ☐ | ☐ | `template-userlist` | `userlist/template_userlist.py` | beta | 290 | — |
| ☐ | ☐ | `template-zapier` | `zapier/template_zapier.py` | stable | 59 | — (needs 0.3) |
| ☐ | ☐ | `template-zendesk` | `zendesk/template_zendesk.py` | beta | 58 | — |
| ☐ | ☐ | `template-mailchimp` | `mailchimp/template_mailchimp.py` | deprecated | 103 | — (delete instead?) |

### Phase 2 — site templates (10), blocked on 0.2

| ✓ | sha? | Template | Python source | Type | Test LOC | Mappings |
| --- | --- | --- | --- | --- | --- | --- |
| ☐ | ☐ | `template-reddit-pixel` | `reddit/template_reddit_pixel.py` | site_destination | 232 | yes |
| ☐ | ☐ | `template-snapchat-pixel` | `snapchat_ads/template_pixel.py` | site_destination | none | yes |
| ☐ | ☐ | `template-tiktok-pixel` | `tiktok_ads/template_tiktok_pixel.py` | site_destination | none | yes |
| ☐ | ☐ | `template-blank-site-destination` | `_internal/template_blank.py` | site_destination | none | yes |
| ☐ | ☐ | `template-blank-site-app` | `_internal/template_blank.py` | site_app | none | — |
| ☐ | ☐ | `template-notification-bar` | `_siteapps/template_notification_bar.py` | site_app | none | — |
| ☐ | ☐ | `template-pineapple-mode` | `_siteapps/template_pineapple_mode.py` | site_app | none | — |
| ☐ | ☐ | `template-early-access-features` | `_siteapps/template_early_access_features.py` | site_app | none | — |
| ☐ | ☐ | `template-hogdesk` | `_siteapps/template_hogdesk.py` | site_app | none | — |
| ☐ | ☐ | `template-debug-posthog-js` | `_siteapps/template_debug_posthog.py` | site_app | none | — |

### Phase 3 — teardown

- [ ] Delete `posthog/cdp/templates/` vendor directories, `_siteapps/`, `_internal/`, `helpers.py`, `test_cdp_templates.py`
- [ ] Strip the Python loop and `TEST_INCLUDE_PYTHON_TEMPLATE_IDS` from `sync_hog_function_templates`
- [ ] Drop `STPyV8` from `pyproject.toml`
- [ ] Confirm `playwright_setup_functions.py` still seeds what E2E needs
- [ ] Update `posthog/cdp/templates/README.md`, or move it to `nodejs/src/cdp/templates/`

## Open questions

- **0.2's transpile approach.** Shelling out to the Python transpiler keeps one implementation but makes Node
  template tests depend on a Python subprocess. Worth deciding whether site templates should instead be
  transpiled in Node long-term, which is a larger change than this migration.
- **`template-mailchimp` is deprecated.** Port or delete? Needs a count of enabled HogFunctions referencing it.
- **The `plugin-*` legacy templates** already live in Node (`nodejs/src/cdp/legacy-plugins/`). Once the Python
  migrators are gone, is there anything left tying legacy plugins to Python beyond `posthog/cdp/migrations.py`?
  Out of scope here, but the answer decides whether that file can go too.
