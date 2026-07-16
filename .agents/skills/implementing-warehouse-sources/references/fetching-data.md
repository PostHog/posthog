# Fetching data: pipeline, incremental, pagination, fan-out

How rows get out of the API and into the pipeline — `source_for_pipeline`, resumable/webhook patterns,
incremental sync, pagination, fan-out endpoints, and retry/throttling.

## Implementing `source_for_pipeline`

Return a `SourceResponse` directly. **Do not** use `dlt_source_to_source_response` for new sources — DLT is being removed.

Prefer yielding data in the shape the API returns it. No custom dataclasses, no heavy parsing. Yield either `dict`, `list[dict]` (preferred when possible), or a `pyarrow.Table`. The pipeline buffers and batches for you.

**Don't import or instantiate `Batcher` at the source layer.** The pipeline already runs one (`pipelines/pipeline/pipeline.py`) at the same 5000-row / 200 MiB thresholds. Yielding raw `dict` / `list[dict]` from your generator is the canonical path — reach for `pyarrow.Table` only when you already have arrow-shaped data (e.g., a ClickHouse adapter). Source-level batching results in double-buffering with no behavioral win.

For pyarrow tables, cap in-memory rows at ~200 MiB or ~5000 rows. Use helpers like `table_from_iterator()` / `table_from_py_list()` from `products/warehouse_sources/backend/temporal/data_imports/pipelines/pipeline/utils.py`.

**URL construction:** use `urllib.parse.urlencode` for query strings. Don't use `requests.Request(...).prepare().url` — `PreparedRequest.url` is typed `Optional[str]` and the typical workaround (`prepared.url or f"..."`) carries an unreachable fallback. `urlencode` is shorter, dependency-free, and produces identical output for ASCII-safe params.

### Resumable source pattern

```python
@dataclasses.dataclass
class MyResumeConfig:
    next_url: str  # or cursor, offset, time window — whatever the API uses

class MySource(ResumableSource[MySourceConfig, MyResumeConfig]):
    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MyResumeConfig]:
        return ResumableSourceManager[MyResumeConfig](inputs, MyResumeConfig)

    def source_for_pipeline(
        self,
        config: MySourceConfig,
        resumable_source_manager: ResumableSourceManager[MyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return my_source(..., resumable_source_manager=resumable_source_manager)
```

In the transport function:

```python
resume = manager.load_state() if manager.can_resume() else None
url = resume.next_url if resume else initial_url

while True:
    data = fetch_page(url)
    # yield batch
    next_url = data.get("links", {}).get("next")
    if not next_url:
        break
    manager.save_state(MyResumeConfig(next_url=next_url))
    url = next_url  # advance before the next fetch, otherwise we loop on the same page
```

Save state **after** yielding each batch, not before — so if we crash we re-yield the last batch (merge dedupes on primary key) rather than skipping it.

### Webhook source pattern

- Implement `webhook_template` returning a `HogFunctionTemplateDC` that transforms incoming webhook payloads.
- Implement `webhook_resource_map` mapping our schema name → external object type.
- Implement `create_webhook`, `delete_webhook`, `get_external_webhook_info` if the API allows programmatic webhook management. Otherwise return a failed result and provide a `webhookSetupCaption` explaining manual setup.
- Add `webhookFields` to `SourceConfig` for post-setup inputs (e.g. signing secret).
- In `source_for_pipeline`, call `self.get_webhook_source_manager(inputs)` and pass its iterator alongside the pull iterator so a single sync pulls historical + webhook-delivered rows.
- Populate `SourceSchema.supports_webhooks=True` only for endpoints where webhooks are actually viable (usually incremental/append-only ones).
- **De-dupe within a webhook batch with a `table_transformer`.** `WebhookSourceManager.get_items()` takes an optional `table_transformer: Callable[[pa.Table], pa.Table]` applied after the raw webhook payloads are deserialized into row dicts. Delta merge only de-dupes _across_ syncs (on `primary_keys`), not within a single source batch — so when one batch can carry multiple events for the same object (e.g. `customer.created` then `customer.updated`), pass a transformer that keeps only the latest version per id. Reference: `_webhook_table_transformer` in `stripe/stripe.py`, wired via `webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)` in `stripe_source`. It groups rows by `object.id`, keeps the one with the greatest event `created` timestamp, and rebuilds the table shaped like the underlying object (ready to merge on `primary_keys=["id"]`).

## Incremental sync guidance

- **Only set `supports_incremental=True` when the API exposes a server-side timestamp filter** (`<field>_gte`, `since`, `modified_after`, etc.). A "client-side cursor" that fetches every page and skips already-seen rows in Python is **not** incremental — every run still hits every page, so the API cost of an "incremental" sync ends up identical to a full refresh. If the API has no server filter, ship full refresh only.
- If the API supports server-side time filtering, use it and map from `db_incremental_field_last_value`.
- **Honor `inputs.incremental_field`** — that's the user's chosen cursor field from the schema settings. `INCREMENTAL_FIELDS` per-endpoint is the menu of _advertised options_; don't reach into `INCREMENTAL_FIELDS[endpoint][0]` to pick a default and silently override the user's selection.
- **Per-endpoint sort enums vary.** Don't hardcode `?sorting=created_at` (or whatever) globally. Verify each list endpoint's allowed sort values against the API spec **and** with a curl smoke-test against the live API — APIs frequently document one set of options and silently reject another, or use a different timestamp column on certain resources.
- **Pass `?sorting=` explicitly on a stable monotonic field when paginating.** For incremental sources, the request sort must match `SourceResponse.sort_mode` (`"asc"` typically; `"desc"` only when forced by the API — see `stripe/stripe.py`, `github/settings.py`) so the pipeline's cursor watermark advances correctly. For full-refresh sources, an explicit sort prevents page-boundary skips/duplicates if the API's implicit default is unstable or shifts as rows are inserted during the sync.
- If the API only supports cursor pagination, still declare incremental fields if reliable and let merge semantics dedupe.
- **`sort_mode` must match the order rows actually arrive in — verify it, don't assume it.** The pipeline trusts `sort_mode="asc"` to checkpoint the incremental watermark after every batch and to allow safe mid-sync worker shutdowns; declaring `asc` while the API returns newest-first corrupts the watermark and breaks resume semantics. Check the API's _default_ sort (it applies when you can't pass `sort`), and remember cursor pagination often rejects or ignores sort params entirely.
- `sort_mode="desc"` only if the endpoint truly cannot return ascending. For descending sources, handle `db_incremental_field_earliest_value` to scroll earlier rows before newer ones (see Stripe).
- **Incremental pagination must terminate at the watermark.** Some APIs reject mixing their time-window filter with cursor pagination, so only the first page is windowed and later pages walk back through history unbounded. If the server can't keep the filter on every page, the paginator must stop client-side once an entire page predates `db_incremental_field_last_value` (see `typeform/typeform.py:TypeformResponsesPaginator`) — otherwise **every incremental sync re-fetches and re-merges each parent's full history**, which is both an API-cost bug and a per-sync memory amplifier.
- Default unknown endpoints to full refresh first; enable incremental only after confirming a stable filter field and API ordering semantics.
- Confirm partition keys against response schemas, not endpoint names.

## Endpoint inventory workflow

- Build an endpoint inventory before expanding coverage (path, auth scopes, grain, pagination style, primary key shape, incremental candidates).
- Keep it in source-local docs (e.g. `products/warehouse_sources/backend/temporal/data_imports/sources/<source>/api_inventory.md`).
- Add endpoints in phases: org-level list endpoints → project-level fan-out → child/fan-out endpoints with bounded pagination.

## Top-level endpoints (org/account level)

- Declare endpoint metadata in `settings.py` (`path`, `primary_key`, `incremental_fields`, `partition_key`, `sort_mode`).
- Build through a single resource config helper; keep transport branches minimal.
- Endpoint params stay declarative (`limit`, required filters).
- Merge write disposition only when incremental semantics are reliable; otherwise full replace.

## Pagination tips

- Some APIs use cursor pagination in `Link` headers — check both `rel="next"` and any results flag.
- When following a full cursor URL from response headers, clear request params in paginator `update_request` to avoid duplicate query params.
- For parent/child fan-out, keep hard page caps per parent resource to avoid unbounded scans.
- Emit structured logs when page caps are reached (include resource name and parent identifiers).

## Fan-out endpoints

Fan-out = iterate a parent resource, then query child endpoints per parent.

**Prefer dependent resources for single-hop fan-out.** Use `rest_api_resources` with a parent and child that declares `type: "resolve"` for the parent field. Shared infra (`rest_source/__init__.py`, `config_setup.process_parent_data_item`) paginates the parent and calls the child per parent row. Use `include_from_parent` so child rows carry parent fields (injected as `_<parent>_<field>` via `make_parent_key_name`).

**Make fan-out declarative.** Add a fan-out config object in `settings.py` (e.g. `DependentEndpointConfig`) with `parent_name`, `resolve_param`, `resolve_field`, `include_from_parent`, optional parent field renames, and optional parent endpoint params. Route single-hop fan-out through a shared helper (e.g. `common/rest_source/fanout.py:build_dependent_resource`).

**Parent field rename mapping belongs in the helper.** Callers should not branch on whether renames exist.

**Per-endpoint pagination/selectors** — `build_dependent_resource` supports endpoint overrides (`parent_endpoint_extra`, `child_endpoint_extra` for `paginator` / `data_selector`, `page_size_param` for non-`limit` size params).

**Path pre-formatting:** `process_parent_data_item` only does `str.format()` with the resolved param. Pre-format static placeholders with `.replace()` before passing to the resource config, so only the resolved placeholder remains.

**Custom iterator only when fan-out is 2+ levels deep.** Reuse the same pagination/retry helpers as elsewhere.

## Retry and throttling strategy

- Use `tenacity` instead of manual retry loops.
- Retry transport failures and retryable status codes (`429`, transient `5xx`).
- Prefer server-provided rate-limit reset headers on `429`; fall back to exponential backoff.
- Bound and make deterministic (`stop_after_attempt`). Preserve clear terminal behavior.
- Keep timeout/retry settings near the top of the module for easy tuning.

The backoff above is the right control when the **customer owns the credential** — their own PAT / API key / OAuth token on their own third-party account, which is nearly every source.
PostHog can't overspend a budget it doesn't own, so honoring `429` / `Retry-After` at the source is enough.

**The exception is a credential PostHog owns and shares across processes** — today that's the PostHog GitHub App installation token (many PostHog subsystems draw from one per-installation budget at once).
There, reactive backoff isn't enough: without coordination, concurrent PostHog callers collectively blow past the shared limit before any `429` comes back.
Those calls must route through [`posthog/egress/`](../../../../posthog/egress/README.md) — a Redis-backed shared budget plus telemetry, gated by construction — never hand-rolled `requests`.
The [GitHub source](../../../../products/warehouse_sources/backend/temporal/data_imports/sources/github/github.py) is the reference: it keys the limiter on the **GitHub App installation id** (the budget owner in GitHub's own id space, not a PostHog DB row), and the customer-PAT path skips the limiter token-blind.
Raw calls to `api.github.com` are blocked by the `github-api-calls-go-through-egress` semgrep rule, so a GitHub-shaped source lands on the egress path by construction.
Deciding question is never "is this a warehouse source?" — it's **"who owns the token, and could concurrent PostHog processes trample each other on it?"**
