# MCP tools

The `autoresearch-*` tool surface. Unusually for a PostHog product, these tools are not primarily for users or for Max — **they are how the training agent operates the product on itself.**

During a run, the sandbox agent has no other write path. It records iterations, materializes features, uploads its bundle, and finalizes its run entirely through these tools. Everything a tool description does not say, the agent has to guess.

## What lives here

- `tools.yaml`
  The whole surface: 29 enabled tools, `category: Autoresearch`, `feature: autoresearch`, `url_prefix: /autoresearch`.
  Each entry names an `operation` (an operation id from the OpenAPI spec), an `enabled` flag, required `scopes` (`autoresearch:read` / `autoresearch:write`), `annotations` (`readOnly`, `destructive`, `idempotent`), and a `title` + `description`.

Tool entries are scaffolded from the OpenAPI schema — `pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all` keeps the tool list and operation ids in sync. Everything editorial (description, title, `enrich_url`, `exclude_params`) is yours to write.

## The two tool families

**Agent-facing** — the training loop's own control surface, backed by `AutoresearchTrainingRunViewSet`:

`autoresearch-training-runs-create`, `-iterations-create`, `-materialize-features`, `-artifacts-upload-create`, `-artifacts-get-create`, `-artifacts-retrieve`, `-artifacts-delete-create`, `-complete-create`, `-history`.

**User-facing** — managing pipelines: `autoresearch-create`, `-list`, `-retrieve`, `-archive-create`, `-pause-create`, `-resume-create`, `-score-create`, `-train-create`, `-models-list`, `-models-retrieve`, `-runs-list`, `-suggestions-*`, `-templates-list`, `-resolve-template-create`, `-validate-*`.

The split matters when you change a description. An agent-facing description is a **contract**: `autoresearch-training-runs-iterations-create` has to tell the agent what a valid `feature_sql` looks like, because the server will reject anything that is not a read-only `SELECT` keyed on `person_id` and the agent has no other way to learn that.

## Descriptions are the product

The descriptions here already do real work, and that is the standard to hold. Examples of what "good" looks like in this file:

- `autoresearch-create` spells out the mutual exclusion — pass `target_event` _or_ `target_definition`, exactly one — and names the next call (`autoresearch-train-create`).
- It also tells the caller to run `autoresearch-validate-create` first _and_ warns that the endpoint does not block on validation errors, so the model knows the check is advisory.
- `autoresearch-archive-create` says what is preserved, that it is reversible only via direct DB access, and points at `pause` as the reversible alternative.

Write for a model that has read nothing else. Name the prerequisite call, the next call, and the failure mode.

## Cross-run memory

These tools are also how a run learns from previous ones. A training agent can call `autoresearch-models-list` and `autoresearch-training-runs-history` on _sibling_ pipelines and build on what already worked — that behavior has been observed in practice, with a run opening by reading an earlier pipeline's champion recipe and using it as its baseline.

That makes the read tools load-bearing for model quality, not just for introspection. Do not disable or narrow them casually.

## Where the rest of the system meets this file

- **Backed by** — `../backend/api/views.py`. A tool is only as good as its serializer annotations; `help_text` and `@extend_schema` flow directly into these schemas.
- **Generated into** — `services/mcp/src/tools/generated/autoresearch.ts` and `services/mcp/src/generated/autoresearch/api.ts`.
- **Consumed by** — the sandbox agent during `../backend/training/` runs, plus any normal MCP client.

## `enrich_url` needs a documented response schema

`enrich_url: '{id}'` makes the generated handler read `result.id`, so the operation's **response** type has to actually carry that field.

This broke once: `autoresearch-create` failed MCP typecheck with `Property 'id' does not exist on type 'AutoresearchPipelineCreate'`. The endpoint returned the read serializer at runtime but only declared the write one, so drf-spectacular typed the response as the request body — which has no `id`. Fixed by declaring `responses={201: AutoresearchPipelineSerializer}` on the viewset's `create`.

If you add `enrich_url` to a tool, check the operation's declared response schema contains the field you interpolate. Fix it on the endpoint and regenerate; never patch the generated file.

## When editing this file

- **Adding an endpoint does not expose it.** A tool exists only once it has an entry here with `enabled: true`.
- Set `scopes` and `annotations` deliberately — `readOnly` and `destructive` change how clients treat a tool.
- Prefer improving the serializer's `help_text` over writing a longer tool description; the serializer feeds the frontend types too, so the fix lands in both places.
- After any change run `pnpm --filter=@posthog/mcp run typecheck` and commit the regenerated files — CI checks for drift.
- **If you add or retire a tool, update this file to match.**
