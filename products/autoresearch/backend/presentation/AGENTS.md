# API

The HTTP surface — and, because of how PostHog's codegen works, considerably more than that.

These serializers are the source of truth for three downstream artifacts: the REST API itself, the generated frontend TypeScript types, and the 29 `autoresearch-*` MCP tools that the sandbox agent uses to drive its own training run.
A vague `help_text` here becomes a vague tool description that a model has to guess at. Treat serializer annotations as agent-facing documentation, because they are.

The `autoresearch-*` MCP tools that expose this API to the sandbox agent arrive at the end of the split tracked in [#88464](https://github.com/PostHog/posthog/pull/88464).

## What lives here

- `views/views.py`
  Five viewsets, registered in `../routes.py` under `project_autoresearch_*` basenames and nested pipeline-first.
  - `AutoresearchPipelineViewSet` — full CRUD plus the lifecycle actions: `train`, `score`, `validate-online`, `archive`, `pause`, `resume`, and the pre-create helpers `templates`, `resolve-template`, `validate`.
  - `AutoresearchTrainingRunViewSet` — read plus create, and **the agent's entire write surface**: `iterations`, `materialize-features`, `complete`, `artifacts`, `artifacts/upload`, `artifacts/get`, `artifacts/delete`, plus `history`.
  - `AutoresearchModelViewSet`, `AutoresearchRunViewSet` — read-only.
  - `AutoresearchSuggestionViewSet` — human or agent hypotheses, plus `respond`.
- `views/serializers.py`
  Request and response shapes, plus `resolve_target()`, which turns a pipeline's `target_event` or `target_definition` (an action reference) into the resolved target the rest of the product uses.

## Access control

Every viewset sets `scope_object = "autoresearch"` and splits `scope_object_read_actions` / `scope_object_write_actions`, so custom actions are classified explicitly rather than inheriting a default.
`AutoresearchAccessPermission` gates on the `autoresearch` feature flag via `../access.py`.

**A new `@action` must be added to one of those two lists.** Omitting it is not a compile error and not a test failure — it is a permissions bug.

## The agent is a client here

This is the part that makes this package unusual. During a training run the sandbox agent is an authenticated API client, and `AutoresearchTrainingRunViewSet` is how it records everything it does:

```text
agent                                    server
  │  POST training_runs/<id>/iterations   →  validated, stored as AutoresearchIteration
  │  POST .../materialize-features        →  features + labels parquet into its sandbox
  │  POST .../artifacts/upload            →  bundle files into object storage
  │  POST .../complete                    →  server-side champion selection
```

Consequences worth internalizing:

- **Everything the agent sends is untrusted.** SQL it submits gets executed; paths it supplies become storage keys. `iterations` runs it through `../training/recipe_validation.py` and `artifacts/upload` through `normalize_artifact_path()` / `MAX_ARTIFACT_BYTES` in `../training/artifacts.py`.
- **The write surface closes when the run does.** `iterations`, `materialize-features`, `complete`, `artifacts/upload`, and `artifacts/delete` all require the run to be RUNNING (or PENDING for `complete`), so a finished run's artifact bundle is frozen — scoring reads it, nothing rewrites it. Artifact reads stay open.
- **`complete` does not accept a champion.** It triggers `complete_training_run()` in `../training/promotion.py`, which picks the champion server-side from the recorded iterations. The agent cannot promote itself.
- **`materialize-features` is sandbox-scoped.** It verifies the sandbox belongs to this training run before writing anything into it.
- If the agent cannot reach these tools, a run burns its full budget doing nothing and fails with `"Agent recorded no iterations before the run ended."` That symptom is almost always MCP connectivity, not the model.

## Where the rest of the system meets this package

- **Routing** — `../routes.py` (`register_routes`), nested pipeline → models / runs / training_runs / suggestions.
- **Frontend types** — generated into `../../frontend/generated/` via drf-spectacular + Orval. Never hand-edit those; change the serializer and regenerate with `hogli build:openapi`.
- **Calls into** — `../training/` (train, complete), `../inference/` (score), `../evaluation/` (validate-online), `../dataset/` (validate, templates, `resolve_target`).

## Declare the response when it differs from the request

`create` validates with `AutoresearchPipelineCreateSerializer` but responds with `AutoresearchPipelineSerializer`. drf-spectacular infers responses from `get_serializer_class()`, so without an explicit `responses=` it documents the _write_ shape as the response.

That broke the MCP build: `autoresearch-create` sets `enrich_url: '{id}'`, the generated handler read `result.id`, and the declared type had no `id`. Now pinned with `@extend_schema(responses={201: AutoresearchPipelineSerializer})`.

Any action whose response shape differs from its request needs the same treatment — the mismatch is invisible in Python and only shows up as a TypeScript error two codegen steps downstream.

## When editing this flow

- **Annotate everything.** `help_text` on fields, `@extend_schema` on custom actions. These flow straight into MCP tool schemas and generated types; an unannotated action produces an empty schema an agent cannot use.
- **Classify every new `@action`** into `scope_object_read_actions` or `scope_object_write_actions`.
- **Validate everything the agent can write**, in the viewset, before it reaches storage or the query engine.
- Regenerate after serializer changes (`hogli build:openapi`) and commit the generated files — CI checks for drift.
- Keep champion selection out of this layer. Endpoints record and trigger; `../training/promotion.py` decides.
- **If you add an endpoint or change the agent's write surface, update this file to match.**
