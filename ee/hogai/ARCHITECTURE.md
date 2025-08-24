## Max AI Architecture

This document explains how Max AI is wired in PostHog. It focuses on the runtime graph, routing, tool calls, query execution and formatting, memory/checkpointing, the LLM wrapper, and frontend integration points.

### Table of Contents

- [Overview](#overview)
- [Runtime Graph (high-level)](#runtime-graph-high-level)
- [Root Orchestration and Routing](#root-orchestration-and-routing)
- [Contextual Tools and MaxTool](#contextual-tools-and-maxtool)
- [Insights Subgraph (RAG → Planner → Generators → Executor)](#insights-subgraph-rag--planner--generators--executor)
- [Query Execution and Formatting](#query-execution-and-formatting)
- [Memory and Checkpointing](#memory-and-checkpointing)
- [LLM Wrapper (MaxChatOpenAI)](#llm-wrapper-maxchatopenai)
- [Frontend Integration (mounting tools)](#frontend-integration-mounting-tools)
- [Tracing, Feature Flags, and Limits](#tracing-feature-flags-and-limits)
- [Key Files](#key-files)

---

### Overview

<details>
<summary>Show overview sequence</summary>

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant FE as Frontend (Max panel / page)
    participant G as LangGraph (AssistantGraph)
    participant R as RootNode
    participant T as Contextual Tools (MaxTool)
    participant I as Insights Subgraph
    participant QE as QueryExecutorNode
    participant AQE as AssistantQueryExecutor
    participant PH as PostHog Query Engine/DB
    participant CK as DjangoCheckpointer

    U->>FE: Message / action
    FE->>G: Start/Resume graph (thread_id, context, tools)
    G->>R: Enter root
    R->>R: Build prompt (core memory, UI context, tool context)
    R->>R: Bind tools, generate (MaxChatOpenAI)
    alt Tool call
        R->>T: Invoke tool (ainvoke)
        T-->>R: Tool result (AssistantToolCallMessage [+ optional ui_payload])
        R->>G: Route next (insights, search, billing, session, docs, end)
    else Just answer
        R-->>G: AssistantMessage
    end
    opt Insights flow
        G->>I: RAG → Planner → Generator → Executor
        I->>QE: Execute
        QE->>AQE: run_and_format_query
        AQE->>PH: process_query_dict / poll
        PH-->>AQE: results
        AQE-->>QE: formatted string (or JSON fallback)
        QE-->>G: AssistantToolCallMessage (bound to tool_call_id)
    end
    G->>CK: Write checkpoint(s)
    G-->>FE: Streamed tokens + tool call messages
    FE-->>U: Render text + UI payload updates
```

</details>

---

### Runtime Graph (high-level)

Backed by LangGraph’s `StateGraph`. The assembled graph adds nodes in this order and compiles with a Django-backed checkpointer.

Files: [graph/graph.py](graph/graph.py), [utils/types/base.py](utils/types/base.py) (node names), [django_checkpoint/checkpointer.py](django_checkpoint/checkpointer.py).

<details>
<summary>Show state graph layout</summary>

```mermaid
flowchart TD
    START([START]) --> TITLE[TitleGenerator]
    TITLE -->|continue| MEM_ONB[MemoryOnboarding]
    MEM_ONB --> MEM_INIT[MemoryInitializer]
    MEM_INIT -->|continue| MEM_ENQ[MemoryOnboardingEnquiry]
    MEM_ENQ --> MEM_FIN[MemoryOnboardingFinalize]
    MEM_FIN -->|continue| ROOT[Root]

    ROOT --> ROOT_TOOLS[RootTools]
    ROOT_TOOLS -->|router| ROUTE{Route}
    ROUTE -->|insights| INSIGHTS([Insights Subgraph])
    ROUTE -->|billing| BILLING[Billing]
    ROUTE -->|insights_search| INSIGHTS_SEARCH[InsightsSearch]
    ROUTE -->|session_summarization| SESSION_SUM[SessionSummarization]
    ROUTE -->|search_documentation| INKEEP[Inkeep Docs]
    ROUTE -->|end| END([END])

    subgraph Insights
        INSIGHTS --> IRAG[Insight RAG Context]
        IRAG --> QP[Query Planner]
        QP --> QP_TOOLS[Query Planner Tools]
        QP_TOOLS -->|trends| TGEN[TrendsGenerator]
        QP_TOOLS -->|funnel| FGEN[FunnelGenerator]
        QP_TOOLS -->|retention| RGEN[RetentionGenerator]
        QP_TOOLS -->|sql| SGEN[SQLGenerator]
        TGEN -->|next| QEXEC[QueryExecutor]
        FGEN -->|next| QEXEC
        RGEN -->|next| QEXEC
        SGEN -->|next| QEXEC
        QEXEC -->|back to| END
    end

    START --> MEM_COLLECT[MemoryCollector]
    MEM_COLLECT --> MEM_COLLECT_TOOLS[MemoryCollectorTools]
    MEM_COLLECT_TOOLS --> MEM_COLLECT
    MEM_COLLECT --> END
```

</details>

---

### Root Orchestration and Routing

Files: [graph/root/nodes.py](graph/root/nodes.py), [llm.py](llm.py), [tool.py](tool.py), [graph/query_executor/nodes.py](graph/query_executor/nodes.py).

What Root does each turn:

- Builds system prompt: base root prompt (feature-flag-trimmed), core memory, contextual tool injections, UI context summary (dashboards, insights, events/actions), billing context.
- Binds tools to the model (`parallel_tool_calls=False`), generates a single step.
- Emits `AssistantMessage` possibly with one `tool_call`.
- `RootNodeTools` executes that tool, appends an `AssistantToolCallMessage`, increments `root_tool_calls_count`, and routes.

Routing decisions (simplified):

- If `root_tool_insight_plan`: go to Insights subgraph
- Else if `search_insights_query`: go to InsightsSearch
- Else if `session_summarization_query`: go to SessionSummarization
- Else if tool was `retrieve_billing_information`: go to Billing
- Else: Inkeep Docs

<details>
<summary>Show root sequence (prompt building → tool → route)</summary>

```mermaid
sequenceDiagram
    autonumber
    participant R as RootNode
    participant M as MaxChatOpenAI
    participant RT as RootTools
    participant D as Docs/Billing/Insights/…

    R->>R: Build system prompt
    R->>M: bind_tools(tools), generate()
    alt Model returns tool_call
        R-->>RT: AssistantMessage(tool_calls=[...])
        RT->>RT: Execute tool (MaxTool or built-in)
        alt navigate
            RT-->>R: NodeInterrupt(AssistantToolCallMessage with ui_payload)
        else regular
            RT-->>R: AssistantToolCallMessage (+update state counters)
        end
        R->>R: Router decides next node
        R-->>D: Transfer control
    else No tool_call
        R-->>D: AssistantMessage to END (or back to ROOT)
    end
```

</details>

---

### Contextual Tools and MaxTool

Files: [tool.py](tool.py), examples of product tools: [products/replay/backend/max_tools.py](../../products/replay/backend/max_tools.py), [products/data_warehouse/backend/max_tools.py](../../products/data_warehouse/backend/max_tools.py), frontend: [frontend/src/scenes/max/MaxTool.tsx](../../frontend/src/scenes/max/MaxTool.tsx), [frontend/src/scenes/max/max-constants.tsx](../../frontend/src/scenes/max/max-constants.tsx).

- `MaxTool` is a LangChain tool base with PostHog context and typed args. It returns both textual content and an artifact (`ui_payload`).
- The root injects each mounted tool’s `root_system_prompt_template` with the frontend-provided context, making the LLM “aware” of which tools are available and when to use them.
- Backend discovery dynamically imports `products/**/backend/max_tools.py` and registers classes in `CONTEXTUAL_TOOL_NAME_TO_TOOL`.
- Special tool: `navigate`. It raises a `NodeInterrupt` to pause the graph so the frontend can remount with a different tool set.

<details>
<summary>Show tool invocation path</summary>

```mermaid
flowchart LR
    A[Root tool_call] --> B{Tool type}
    B -->|built-in| BI[search_docs / billing / search_insights / session_summarization]
    B -->|contextual| CT[MaxTool subclass]
    CT --> CTIN[format_system_prompt_injection]
    CT --> CTRUN[_arun_impl]
    CTRUN --> OUT[content and artifact]
    OUT --> M[AssistantToolCallMessage]
    M -->|visible? ui_payload?| RootTools
    BI --> RootTools
```

</details>

---

### Insights Subgraph (RAG → Planner → Generators → Executor)

Files: [graph/graph.py](graph/graph.py), directories: [graph/query_planner/](graph/query_planner/), [graph/trends/](graph/trends/), [graph/funnels/](graph/funnels/), [graph/retention/](graph/retention/), [graph/sql/](graph/sql/), [graph/rag/](graph/rag/).

- RAG: retrieves local insight context to ground generation.
- Planner: iterates a plan; tools can refine the plan.
- Generators: produce `Assistant*Query` types (Trends, Funnels, Retention, HogQL).
- Executor: runs and formats the query, responding as a tool result so the original tool call chain stays consistent.

<details>
<summary>Show insights subgraph orchestration</summary>

```mermaid
stateDiagram-v2
    [*] --> InsightRAG
    InsightRAG --> Planner
    Planner --> PlannerTools
    PlannerTools --> Planner: continue
    Planner --> Trends: trends
    Planner --> Funnels: funnel
    Planner --> Retention: retention
    Planner --> SQL: sql
    Trends --> QueryExecutor
    Funnels --> QueryExecutor
    Retention --> QueryExecutor
    SQL --> QueryExecutor
    QueryExecutor --> [*]
```

</details>

---

### Query Execution and Formatting

Files: [graph/query_executor/nodes.py](graph/query_executor/nodes.py), [graph/query_executor/query_executor.py](graph/query_executor/query_executor.py), [graph/query_executor/format.py](graph/query_executor/format.py).

Key points:

- Executes via `process_query_dict` (blocking or async-polled) with product tag `MAX_AI`.
- Formats with type-specific formatters: Trends, Funnels (time-aware), Retention, SQL (uses `columns`).
- If formatting raises, falls back to compact JSON of `results`.
- `QueryExecutorNode` crafts a single `AssistantToolCallMessage` addressed to the original `tool_call_id`.

<details>
<summary>Show execution flow</summary>

```mermaid
flowchart TD
    A[VisualizationMessage with Assistant*Query] --> B[AssistantQueryExecutor]
    B --> C{Execution mode}
    C -->|prod| C1[RECENT_CACHE_CALCULATE_ASYNC_IF_STALE]
    C -->|tests| C2[CALCULATE_BLOCKING_ALWAYS]
    C1 --> D[process_query_dict]
    C2 --> D
    D --> E{Async query_status?}
    E -->|yes| P[poll get_query_status until complete or timeout]
    E -->|no| F[results]
    P --> F
    F --> G{Formatter by type}
    G -->|Trends| FT[TrendsResultsFormatter]
    G -->|Funnels| FF[FunnelResultsFormatter]
    G -->|Retention| FR[RetentionResultsFormatter]
    G -->|SQL| FS[SQLResultsFormatter]
    FT --> H[formatted string]
    FF --> H
    FR --> H
    FS --> H
    G -->|Exception| J[fallback JSON results]
    H --> K[AssistantToolCallMessage]
    J --> K
```

</details>

---

### Memory and Checkpointing

Files: [graph/memory/](graph/memory/), [django_checkpoint/checkpointer.py](django_checkpoint/checkpointer.py), [ee/models/assistant.py](../models/assistant.py) (DB models referenced).

- Memory nodes handle onboarding Q&A and collection of user facts. They can write messages with tool calls to staged memory.
- `DjangoCheckpointer` persists LangGraph checkpoints and channel blobs into Postgres, keyed by `thread_id` and `checkpoint_ns`. It supports list/get/put/put_writes.
- Checkpoints store `pending_sends`, `channel_versions` and per-channel serialized blobs.

<details>
<summary>Show checkpoint write path</summary>

```mermaid
sequenceDiagram
    autonumber
    participant G as LangGraph Runtime
    participant CP as DjangoCheckpointer
    participant DB as Postgres (ConversationCheckpoint*)

    G->>CP: aput(config, checkpoint, metadata, new_versions)
    CP->>CP: split channel_values
    CP->>DB: upsert ConversationCheckpoint (parent_checkpoint_id, checkpoint, metadata)
    CP->>DB: bulk_create ConversationCheckpointBlob (channel/version/type/blob)
    DB-->>CP: ok
    CP-->>G: next_config (checkpoint_id)

    G->>CP: aput_writes(config, writes, task_id)
    CP->>DB: get_or_create ConversationCheckpoint
    CP->>DB: bulk_create ConversationCheckpointWrite (task_id, idx, channel, blob)
    DB-->>CP: ok
    CP-->>G: done
```

</details>

---

### LLM Wrapper (MaxChatOpenAI)

Files: [llm.py](llm.py).

- Injects project/org/user/datetime/region into the system instructions.
- Works for both classic Chat Completions message lists and the Responses API (`instructions`).
- Ensures consistent retries and context for every generation across nodes.

<details>
<summary>Show message enrichment</summary>

```mermaid
flowchart LR
    A[messages] --> B{use responses api}
    B -->|no| C[_enrich_messages insert system block]
    B -->|yes| D[_enrich_responses_api_model_kwargs append to instructions]
    C --> E[super generate]
    D --> E
```

</details>

---

### Frontend Integration (mounting tools)

Files: [README.md](README.md) (MaxTool how-to), frontend: [frontend/src/scenes/max/MaxTool.tsx](../../frontend/src/scenes/max/MaxTool.tsx), [frontend/src/scenes/max/max-constants.tsx](../../frontend/src/scenes/max/max-constants.tsx), [frontend/src/queries/schema/schema-assistant-messages.ts](../../frontend/src/queries/schema/schema-assistant-messages.ts), product tools examples: [products/replay/backend/max_tools.py](../../products/replay/backend/max_tools.py), [products/data_warehouse/backend/max_tools.py](../../products/data_warehouse/backend/max_tools.py).

- Frontend mounts a `MaxTool` React component around UI, passing `context` and `callback`.
- The backend tool’s `root_system_prompt_template` is injected at root time, and the tool’s args schema governs how the LLM calls it.
- Only tools mounted in the current scene are bound, so availability is scene-aware by design.

<details>
<summary>Show FE ↔ BE tool wiring</summary>

```mermaid
flowchart TD
    FE[MaxTool name=... context=...] --> RTD[TOOL_DEFINITIONS metadata]
    FE --> SCHEMA[AssistantContextualTool enum]
    SCHEMA --> GEN[pnpm schema:build]
    GEN --> TS[TS/Schema types for FE]
    FE --> SRV[POST /api/max_tools when applicable]
    SRV --> BE[products/.../backend/max_tools.py]
    BE --> REG[CONTEXTUAL_TOOL_NAME_TO_TOOL]
    REG --> ROOT[Root.bind_tools]
```

</details>

---

### Tracing, Feature Flags, and Limits

- Tracing: local LLM analytics at `http://localhost:8010/llm-analytics/traces`.
- Feature flags gate optional capabilities in the root prompt and tool set (e.g. `max-ai-insight-search`, `max-session-summarization`).
- Limits: token window trimming to ~32k when >64k, and `MAX_TOOL_CALLS=4` to break loops.

---

### Key Files

- Graph composition: [graph/graph.py](graph/graph.py)
- Root and routing: [graph/root/nodes.py](graph/root/nodes.py)
- Query execution: [graph/query_executor/nodes.py](graph/query_executor/nodes.py), [graph/query_executor/query_executor.py](graph/query_executor/query_executor.py), [graph/query_executor/format.py](graph/query_executor/format.py)
- Memory: [graph/memory/](graph/memory/)
- Checkpointing: [django_checkpoint/checkpointer.py](django_checkpoint/checkpointer.py)
- LLM wrapper: [llm.py](llm.py)
- Tools: [tool.py](tool.py), examples: [products/replay/backend/max_tools.py](../../products/replay/backend/max_tools.py), [products/data_warehouse/backend/max_tools.py](../../products/data_warehouse/backend/max_tools.py)
- Frontend: [frontend/src/scenes/max/](../../frontend/src/scenes/max/), [frontend/src/queries/schema/schema-assistant-messages.ts](../../frontend/src/queries/schema/schema-assistant-messages.ts), [frontend/src/scenes/max/max-constants.tsx](../../frontend/src/scenes/max/max-constants.tsx)

---

If you need more depth on prompts or adding new query types, see [README.md](README.md) and [PROMPTING_GUIDE.md](PROMPTING_GUIDE.md).


