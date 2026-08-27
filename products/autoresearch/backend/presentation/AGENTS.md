# API

The HTTP surface — and, because of how PostHog's codegen works, considerably more than that.

These serializers are the source of truth for three downstream artifacts: the REST API itself, the generated frontend TypeScript types, and the 29 `autoresearch-*` MCP tools that the sandbox agent uses to drive its own training run.
A vague `help_text` here becomes a vague tool description that a model has to guess at. Treat serializer annotations as agent-facing documentation, because they are.

This package lands one endpoint group at a time. Pipeline CRUD and the pre-create helpers are here; the lifecycle actions, the read-only model and run viewsets, the training-run agent surface, and suggestions arrive in later pieces of the split tracked in [#88464](https://github.com/PostHog/posthog/pull/88464). The MCP tools arrive at the end of it.

## What lives here

- `views/views.py`
  One viewset so far, registered in `../routes.py` under the `project_autoresearch_pipelines` basename.
  - `AutoresearchPipelineViewSet` — full CRUD plus the pre-create helpers `templates`, `resolve-template`, `validate`.
- `views/serializers.py`
  Request and response shapes, plus `resolve_target()`, which turns a pipeline's `target_event` or `target_definition` (an action reference) into the resolved target the rest of the product uses.

## Access control

Every viewset sets `scope_object = "autoresearch"` and splits `scope_object_read_actions` / `scope_object_write_actions`, so custom actions are classified explicitly rather than inheriting a default.
`AutoresearchAccessPermission` gates on the `autoresearch` feature flag via `../access.py`.

**A new `@action` must be added to one of those two lists.** Omitting it is not a compile error and not a test failure — it is a permissions bug.

## Where the rest of the system meets this package

- **Routing** — `../routes.py` (`register_routes`).
- **Frontend types** — generated into `../../frontend/generated/` via drf-spectacular + Orval. Never hand-edit those; change the serializer and regenerate with `hogli build:openapi`.
- **Calls into** — `../dataset/` (validate, templates, `resolve_target`).

## Declare the response when it differs from the request

`create` validates with `AutoresearchPipelineCreateSerializer` but responds with `AutoresearchPipelineSerializer`. drf-spectacular infers responses from `get_serializer_class()`, so without an explicit `responses=` it documents the _write_ shape as the response.

That broke the MCP build: `autoresearch-create` sets `enrich_url: '{id}'`, the generated handler read `result.id`, and the declared type had no `id`. Now pinned with `@extend_schema(responses={201: AutoresearchPipelineSerializer})`.

Any action whose response shape differs from its request needs the same treatment — the mismatch is invisible in Python and only shows up as a TypeScript error two codegen steps downstream.

## When editing this flow

- **Annotate everything.** `help_text` on fields, `@extend_schema` on custom actions. These flow straight into MCP tool schemas and generated types; an unannotated action produces an empty schema an agent cannot use.
- **Classify every new `@action`** into `scope_object_read_actions` or `scope_object_write_actions`.
- Regenerate after serializer changes (`hogli build:openapi`) and commit the generated files — CI checks for drift.
- **If you add an endpoint, update this file to match.**
