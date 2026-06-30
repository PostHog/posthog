# Endpoint coverage: inventory, top-level, fan-out, and pagination

## Endpoint inventory workflow

- Build an endpoint inventory before expanding coverage (path, auth scopes, grain, pagination style, primary key shape, incremental candidates).
- Keep it in source-local docs (e.g. `products/warehouse_sources/backend/temporal/data_imports/sources/<source>/api_inventory.md`).
- Add endpoints in phases: org-level list endpoints → project-level fan-out → child/fan-out endpoints with bounded pagination.

## Top-level endpoints (org/account level)

- Declare endpoint metadata in `settings.py` (`path`, `primary_key`, `incremental_fields`, `partition_key`, `sort_mode`).
- Build through a single resource config helper; keep transport branches minimal.
- Endpoint params stay declarative (`limit`, required filters).
- Merge write disposition only when incremental semantics are reliable; otherwise full replace.

## Fan-out endpoints

Fan-out = iterate a parent resource, then query child endpoints per parent.

**Prefer dependent resources for single-hop fan-out.** Use `rest_api_resources` with a parent and child that declares `type: "resolve"` for the parent field. Shared infra (`rest_source/__init__.py`, `config_setup.process_parent_data_item`) paginates the parent and calls the child per parent row. Use `include_from_parent` so child rows carry parent fields (injected as `_<parent>_<field>` via `make_parent_key_name`).

**Make fan-out declarative.** Add a fan-out config object in `settings.py` (e.g. `DependentEndpointConfig`) with `parent_name`, `resolve_param`, `resolve_field`, `include_from_parent`, optional parent field renames, and optional parent endpoint params. Route single-hop fan-out through a shared helper (e.g. `common/rest_source/fanout.py:build_dependent_resource`).

**Parent field rename mapping belongs in the helper.** Callers should not branch on whether renames exist.

**Per-endpoint pagination/selectors** — `build_dependent_resource` supports endpoint overrides (`parent_endpoint_extra`, `child_endpoint_extra` for `paginator` / `data_selector`, `page_size_param` for non-`limit` size params).

**Path pre-formatting:** `process_parent_data_item` only does `str.format()` with the resolved param. Pre-format static placeholders with `.replace()` before passing to the resource config, so only the resolved placeholder remains.

**Custom iterator only when fan-out is 2+ levels deep.** Reuse the same pagination/retry helpers as elsewhere.

## Pagination tips

- Some APIs use cursor pagination in `Link` headers — check both `rel="next"` and any results flag.
- When following a full cursor URL from response headers, clear request params in paginator `update_request` to avoid duplicate query params.
- For parent/child fan-out, keep hard page caps per parent resource to avoid unbounded scans.
- Emit structured logs when page caps are reached (include resource name and parent identifiers).
