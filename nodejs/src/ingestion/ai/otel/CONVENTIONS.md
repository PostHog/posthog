# OTel GenAI Semantic Conventions — Landscape and Compatibility Guide

## Why conventions diverge

The official OTel GenAI semantic conventions (`gen_ai.*` namespace) were introduced in May 2024 (semconv v1.26.0).
`gen_ai.operation.name` specifically was added in August 2024 (v1.27.0).

However, Traceloop's OpenLLMetry project started instrumenting LLM frameworks in 2023 — before any official spec existed.
They created their own `llm.*` and `traceloop.*` namespaces.
When the official spec arrived, Traceloop partially migrated: core attributes moved to `gen_ai.*`,
but `llm.request.type` and several other `llm.*` attributes were never migrated.
As of March 2026, `llm.request.type` remains the only way to determine operation type from Traceloop instrumentation.

The Vercel AI SDK took a different path, creating a custom `ai.*` namespace.
They overlay some `gen_ai.*` attributes but most data lives in `ai.*`.

## Convention generations we handle

### Generation 1 — Traceloop/OpenLLMetry (pre-spec)

Used by: `opentelemetry-instrumentation-langchain`, `-openai`, `-anthropic`, `-cohere`, `-bedrock`, `-vertexai`, and ~20 more.

| Concept | Attribute | Values |
|---|---|---|
| Operation type | `llm.request.type` | `chat`, `completion`, `embedding`, `rerank`, `unknown` |
| Provider | `gen_ai.system` | `openai`, `Anthropic`, etc. |
| Input tokens | `gen_ai.usage.prompt_tokens` + `gen_ai.usage.input_tokens` | Both set |
| Output tokens | `gen_ai.usage.completion_tokens` + `gen_ai.usage.output_tokens` | Both set |
| Input content | `gen_ai.prompt.{i}.role` + `gen_ai.prompt.{i}.content` | Flattened per-message |
| Output content | `gen_ai.completion.{i}.role` + `gen_ai.completion.{i}.content` | Flattened per-message |
| Tool definitions | `llm.request.functions.{i}.name/description/parameters` | Flattened |
| Workflow type | `traceloop.span.kind` | `workflow`, `task`, `agent`, `tool` |

### Generation 2 — OTel spec v1.26–v1.36

Used by: Pydantic AI (Logfire), `opentelemetry-instrumentation-openai-v2`, LiteLLM.

| Concept | Attribute | Values |
|---|---|---|
| Operation type | `gen_ai.operation.name` | `chat`, `text_completion`, `embeddings`, `execute_tool`, `create_agent`, `invoke_agent` |
| Provider | `gen_ai.system` | Well-known values |
| Input tokens | `gen_ai.usage.input_tokens` | |
| Output tokens | `gen_ai.usage.output_tokens` | |
| Input content | `gen_ai.input.messages` | JSON array |
| Output content | `gen_ai.output.messages` | JSON array |

### Generation 3 — OTel spec v1.37+ (latest)

Same as generation 2 except:

- `gen_ai.system` renamed to `gen_ai.provider.name`
- Agent-specific attributes: `gen_ai.agent.name`, `gen_ai.agent.id`, `gen_ai.conversation.id`

## Value mapping differences

| OTel spec `gen_ai.operation.name` | Traceloop `llm.request.type` |
|---|---|
| `chat` | `chat` |
| `text_completion` | `completion` |
| `embeddings` (plural) | `embedding` (singular) |
| `execute_tool` | _(no equivalent, uses `traceloop.span.kind = tool`)_ |
| `create_agent` / `invoke_agent` | _(no equivalent, uses `traceloop.span.kind = agent`)_ |

## What we normalize

In `attribute-mapping.ts`:

- `llm.request.type` → event reclassification (same logic as `gen_ai.operation.name`)
- `gen_ai.usage.prompt_tokens` → `$ai_input_tokens` (fallback)
- `gen_ai.usage.completion_tokens` → `$ai_output_tokens` (fallback)
- `gen_ai.system` → `$ai_provider` (fallback for `gen_ai.provider.name`)

In Traceloop middleware:

- Flattened `gen_ai.prompt.{i}.*` → `$ai_input` (structured JSON array)
- Flattened `gen_ai.completion.{i}.*` → `$ai_output_choices` (structured JSON array)
- Flattened `llm.request.functions.{i}.*` → `$ai_tools`

## Things to watch

1. **Traceloop migration to `gen_ai.operation.name`**:
   [Issue #3515](https://github.com/traceloop/openllmetry/issues/3515) tracks migration of deprecated attributes.
   If/when they migrate, our `llm.request.type` fallback becomes a no-op (harmless).

2. **Traceloop migration to structured messages**:
   They still emit `gen_ai.prompt.{i}.*` (deprecated since OTel v1.28.0) instead of `gen_ai.input.messages`.
   If they migrate, the generic `ATTRIBUTE_MAP` will handle it and our reassembly becomes a no-op.

3. **`gen_ai.system` → `gen_ai.provider.name` migration**:
   Most instrumentors still emit the deprecated `gen_ai.system`.
   Pydantic AI and openai-v2 now emit both. We handle both via primary + fallback maps.

4. **New `gen_ai.operation.name` values**:
   The spec keeps adding values (`execute_tool`, `create_agent`, `invoke_agent`, `retrieval`).
   Unknown values fall through to `$ai_span`, which is correct default behavior.

5. **Vercel AI SDK** (`ai.*` namespace):
   Not handled yet. Uses custom `ai.prompt.messages`, `ai.response.text`, `ai.model.id`.
   Does not set `gen_ai.operation.name` or `llm.request.type`.
   Would need span name-based classification (`ai.generateText` → generation).
   Tracked separately.

6. **OTel semconv stability**:
   Nothing in the GenAI conventions has reached "Stable" status.
   Expect continued renames and restructuring.
   The `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` env var
   controls which convention version instrumentors emit.
