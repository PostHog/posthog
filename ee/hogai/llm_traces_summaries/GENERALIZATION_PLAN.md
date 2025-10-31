# LLM Traces Summarization - Generalization Plan

## Status: Draft - For Discussion

This document outlines the plan to generalize the LLM traces summarization feature from its current PostHog AI-specific implementation to work with any LLMA (LLM Analytics) traces.

## Current State (MVP)

### What Works

- ✅ Analyzes PostHog AI chat traces (LangGraph-based)
- ✅ Generates issue summaries using Gemini
- ✅ Creates embeddings for semantic search
- ✅ Clusters similar issues using KMeans
- ✅ Integrates with PostHog AI chat (Max)
- ✅ Creates summary notebooks

### Critical Limitation

**The current implementation is ~95% PostHog AI-specific** and cannot process standard LLMA traces.

#### Domain-Specific Encoding

**Location**: `ee/hogai/llm_traces_summaries/tools/stringify_trace.py`

**Problem**: Expects PostHog AI's custom message structure:

```python
messages = trace.outputState.get("messages")  # ❌ Not in standard LLMA
```

**What it assumes**:

1. `outputState.messages` structure exists (not standard LLMA)
2. Message types: `ai`, `human`, `tool`, `context`, `answer` (PostHog AI specific)
3. Tool call format: PostHog AI's structure
4. Chat-like alternating human/ai interaction
5. UI navigation concepts (`ui_payload`)

**What standard LLMA provides**:

```python
LLMTrace {
    events: [
        {
            event: "$ai_generation",  # or "$ai_span"
            properties: {
                "$ai_input": "...",
                "$ai_output": "...",
                "$ai_model": "gpt-4",
                "$ai_error": "...",
                # ... standard LLMA properties
            }
        }
    ]
}
```

## Solution: Generic Text Representation

### Key Insight from PR #40502

PR #40502 builds **generic text formatters** that work with standard LLMA properties:

- `formatGenerationTextRepr()` - Formats any `$ai_generation` event
- `formatSpanTextRepr()` - Formats any `$ai_span` event
- `formatTraceTextRepr()` - Formats entire trace with hierarchy
- Works with `$ai_input`, `$ai_output`, `$ai_tools`, etc.

## Analysis Themes: Multi-Dimensional Trace Analysis

### The Concept

Instead of running a single analysis pass over traces, we introduce **Analysis Themes** - different analytical perspectives applied to traces:

- **Error Analysis Theme**: Find errors, exceptions, and failures
- **UX Issues Theme**: Identify friction points and frustrations
- **Feature Requests Theme**: Extract suggestions and improvement ideas
- **Performance Theme**: Detect latency, cost, and efficiency problems
- **Success Patterns Theme**: Identify what works well

### Why Themes Matter

**One Trace → Multiple Insights**

```text
Trace: User checkout flow
├── Error Theme: "Payment API timeout after 30s"
├── UX Theme: "User confused by shipping options UI"
├── Feature Theme: "User requested Apple Pay support"
└── Performance Theme: "Checkout took 3.2s (2x average)"
```

**Theme-Specific Trace Filtering**

Each theme can target specific trace subsets for efficiency and quality:

```python
# Example: Payment errors theme
PaymentErrorsTheme:
  base_filters: [$ai_span_name = 'checkout']  # All checkout traces
  theme_filters: [$ai_error ilike '%payment%'] # Only payment errors
  prompt: "Analyze payment error patterns..."

# Example: Docs UX theme
DocsUXTheme:
  base_filters: [$ai_span_name = 'docs_chat']  # Docs traces only
  theme_filters: []  # All docs traces
  prompt: "Identify documentation UX issues..."
```

### Generalization Strategy

**Core Principle**: Universal stringification (generic LLMA formatter for all traces) + flexible analysis themes with custom prompts.

## Implementation Phases

### Phase 1: Universal Text Representation (1-2 weeks)

**Goal**: Adopt generic LLMA stringifier for all traces (via PR #40502 endpoint)

**v1 Approach**: Use **only** the generic LLMA stringifier - no UI for stringifier selection. Domain expertise comes from custom analysis prompts, not custom stringifiers.

**Rationale**:

- **Dogfooding**: Everyone uses the same stringifier → easier to validate
- **Simplicity**: No UI/API complexity for stringifier selection in v1
- **Flexibility**: Domain-specific analysis via theme prompts
- **Future-ready**: Architecture allows pluggable stringifiers later

#### 1.1 Integrate Generic LLMA Stringifier

- [ ] Use general-purpose stringify endpoint from PR #40502
- [ ] Support standard LLMA properties: `$ai_input`, `$ai_output`, `$ai_tools`, `$ai_error`
- [ ] Handle multiple message formats (OpenAI, Anthropic, LangChain)
- [ ] Preserve trace hierarchy (spans within traces)

#### 1.2 Testing

- [ ] Test with OpenAI API traces
- [ ] Test with Anthropic API traces
- [ ] Test with LangChain traces
- [ ] Test with PostHog AI traces (regression)
- [ ] Compare output quality across different trace types

**Success Criteria**:

- Any LLMA trace can be converted to readable text
- Text representation captures errors, tool usage, conversation flow
- No loss of important information

### Phase 2: Analysis Themes & Configurable Pipelines (2-3 weeks)

**Goal**: Allow users to configure theme-based analysis workflows

#### 2.1 Analysis Theme Configuration

- [ ] Create `AnalysisTheme` dataclass
  - `theme_id: str` - Unique identifier (e.g., "payment_errors")
  - `name: str` - Display name
  - `description: str` - User-facing description
  - `base_filters: list[HogQLPropertyFilter]` - Team-wide trace filters
  - `theme_filters: list[HogQLPropertyFilter]` - Theme-specific filters
  - `sample_rate: float` - Random sampling (0.0-1.0) for cost control
  - `sample_seed: int` - Deterministic sampling seed
  - `prompt: str` - LLM analysis prompt (returns JSON with theme_relevant + summary)
  - `date_range: DateRange` - Time window
  - `clustering_config: ClusteringConfig` - Clustering parameters
  - Note: v1 uses generic LLMA stringifier for all (no stringifier_type field)

#### 2.2 Per-Theme Trace Collection

- [ ] Implement theme-based collector
  - Combine base_filters + theme_filters for efficiency
  - Collect traces only for relevant themes
  - Apply sampling if configured (sample_rate < 1.0)
  - Cache stringified traces to avoid duplication
- [ ] Add trace text caching layer
  - Store `{trace_id: text_repr}` in Redis with 24h TTL
  - Reuse across themes that analyze same traces
  - Track cache hit rates for optimization

#### 2.3 Built-In Themes

- [ ] Ship with standard themes:
  - `error_analysis` - Find and categorize errors
  - `ux_issues` - Identify friction points and frustrations
  - `feature_requests` - Extract feature requests
  - `success_patterns` - Identify what works well
  - `performance_issues` - Find latency/cost problems
- [ ] Allow custom themes via config

#### 2.4 Prompt Templates

- [ ] Create prompt template system for themes
- [ ] Built-in templates for each theme type
- [ ] Support custom prompts from config
- [ ] Validation that prompt works with trace text format

#### 2.5 Batching Strategy

- [ ] Implement Temporal workflow for batch processing
  - Run every 10 minutes (configurable)
  - Collect traces from last time window
  - Analyze all enabled themes in sequence
  - Handle failures gracefully (skip failed traces)
- [ ] Batch LLM calls (100 traces at a time)
- [ ] Batch embedding generation (send to Kafka in bulk)

#### 2.6 Storage as PostHog Events

- [ ] Store summaries as `$ai_trace_summary` events (native PostHog approach)
  - Properties: `$trace_id`, `$analysis_theme_id`, `$summary`, metadata
  - Uses existing event ingestion pipeline
  - Can query like any LLMA event
  - Scales automatically with ClickHouse
- [ ] Migration path from PostgreSQL (dual-write, then cutover)
- [ ] Update embeddings to use theme-scoped rendering:
  - `rendering: f"llm_traces_summary_{theme_id}"`
  - Each theme gets its own embedding space (namespace in document_embeddings)

#### 2.7 Config Storage

- [ ] Store theme configs in team settings
- [ ] API endpoints for CRUD operations on themes
- [ ] Migration for existing PostHog AI config → theme

**Success Criteria**:

- Users can define multiple analysis themes per project
- Themes run independently with separate filtering
- 70%+ cost reduction vs. naive approach (all traces × all themes)
- Clear separation between themes (embeddings, clusters, summaries)

### Phase 3: User Interface (3-4 weeks)

**Goal**: Let users configure and manage analysis themes through UI

#### 3.1 Analysis Themes Manager

- [ ] Settings page: LLM Analytics → Analysis Themes
- [ ] Theme list view:
  - Show all themes (built-in + custom)
  - Status indicators (enabled/disabled)
  - Last run timestamp
  - Number of traces analyzed
  - Toggle theme on/off
- [ ] Create/Edit theme form:
  - Name and description
  - **Base filters** (standard PostHog property filter UI)
  - **Theme-specific filters** (additional filters for this theme only)
  - Prompt template (with built-in options)
  - Schedule (manual, daily, weekly)
  - Date range
- [ ] Pre-built theme templates (errors, UX issues, feature requests, etc.)
- [ ] Test theme button (run on sample traces, show expected trace count)

#### 3.2 Theme Filtering UI

- [ ] Reuse standard PostHog property filter builder
  - Users already familiar with this UI
  - Supports all LLMA properties (`$ai_*`)
  - Auto-complete for property names
  - Preview trace count before running
- [ ] Base vs. Theme filter explanation:
  - "Base filters apply to all themes (optional)"
  - "Theme filters narrow down to specific traces for this theme"
  - Show combined filter preview

#### 3.3 Results Dashboard

- [ ] View analysis results **per theme**
- [ ] Theme selector/tabs
- [ ] Cluster visualization per theme
- [ ] Trend over time (theme-specific)
- [ ] Export to notebook
- [ ] Share results with team
- [ ] Cross-theme insights (same trace, multiple themes)

**Success Criteria**:

- Non-technical users can create custom themes
- Filtering UI is familiar (standard PostHog filters)
- Clear preview of what traces will be analyzed
- Easy to iterate on prompts and filters
- Obvious cost implications (trace count estimates)

### Phase 4: Advanced Features (Future)

**Goal**: Power user capabilities and optimizations

#### 4.1 Theme Orchestration

- [ ] Parallel theme execution (separate Temporal workers)
- [ ] Smart scheduling (run expensive themes off-peak)
- [ ] Progressive results (stream theme results as they complete)
- [ ] Cross-theme dependencies (one theme triggers another)

#### 4.2 Advanced Theme Configuration

- [ ] Multi-step theme pipelines:
  - Extract topics → Cluster → Generate names → Find root causes
- [ ] Custom clustering per theme:
  - Configurable algorithms (KMeans, DBSCAN, etc.)
  - User-defined cluster count
  - Custom similarity functions
- [ ] Theme templates marketplace (community-contributed)

#### 4.3 Automated Actions

- [ ] Theme-based alerts:
  - "Alert when error_analysis cluster exceeds 100 traces"
  - "Notify when ux_issues cluster grows >50% week-over-week"
- [ ] Auto-create issues in GitHub/Linear from theme clusters
- [ ] Slack notifications for new patterns per theme
- [ ] Auto-tag traces based on theme analysis

#### 4.4 Performance Optimizations

- [ ] Move from PSQL to ClickHouse for summaries (FTS)
- [ ] Incremental updates:
  - Don't re-summarize existing traces
  - Only analyze new traces since last run
  - Track processed trace IDs per theme
- [ ] Smarter caching:
  - Persist stringified traces across runs
  - Cache embeddings per trace (not per theme if same text)
  - LRU cache for frequently accessed summaries

## Migration Strategy

### Backward Compatibility

**v1 Approach**: Migrate existing PostHog AI workflow to use generic LLMA stringifier

1. **Existing workflow becomes first theme**: "Unhappy Users" (Max AI) theme
    - Filters: `generation_name = 'MaxAIAgent.generate'`
    - Same prompt as current implementation
    - Uses generic LLMA stringifier (not PostHog AI specific)
2. **Benefits of universal stringifier**:
    - Simpler codebase (one stringifier to maintain)
    - Better dogfooding (everyone uses same system)
    - Existing summaries can be regenerated if needed
3. **Migration risk**: Low - generic stringifier handles all LLMA traces including PostHog AI format

### Data Migration

1. **Phase 1**: No schema changes - leverage existing tables
2. **Phase 2**: Add `AnalysisThemeConfig` Django model
3. **Phase 3**: Migrate existing summaries to new theme-based events (optional)

### Deployment

1. **Phase 1**: Backend-only, feature-flagged
2. **Phase 2**: API + minimal UI for internal testing
3. **Phase 3**: Full UI rollout
4. **Phase 4**: Opt-in advanced features

## Success Metrics

### Phase 1

- [ ] Can process 100% of standard LLMA traces (not just PostHog AI)
- [ ] Text representation quality equal or better than current
- [ ] No regression in PostHog AI trace processing
- [ ] Stringified trace format works with multiple LLM providers

### Phase 2

- [ ] 5+ built-in analysis themes available
- [ ] Users can create custom themes via API
- [ ] Multiple themes run independently without conflicts
- [ ] 70%+ cost reduction with theme-filtered collection vs. naive approach
- [ ] Trace text caching reduces duplicate stringification by 80%+
- [ ] Theme-scoped embeddings enable separate similarity spaces
- [ ] Batching workflow runs reliably every 10 minutes
- [ ] Sampling (10% rate) provides sufficient pattern detection with 90% cost savings
- [ ] Summaries stored as `$ai_trace_summary` events queryable like other LLMA events

### Phase 3

- [ ] 5+ teams using custom themes in production
- [ ] Average time to create theme < 10 minutes
- [ ] User feedback: "Familiar filtering UI", "Easy to understand themes"
- [ ] Trace count preview helps users estimate costs before running
- [ ] Cross-theme insights provide valuable multi-dimensional analysis

### Phase 4

- [ ] Parallel theme execution reduces total analysis time by 60%+
- [ ] Incremental updates process only new traces (10x speedup)
- [ ] Theme-based alerts catch issues 50% faster
- [ ] Performance improvements: 50% faster clustering per theme
- [ ] Integration with 3+ external tools (GitHub, Linear, Slack)

## Rough Cost Estimation

**Important**: These are ballpark estimates for planning purposes only. Actual costs will vary significantly based on:

- LLM model selection and pricing (which changes frequently)
- Token usage per trace (depends on trace complexity and length)
- Embedding model costs
- Volume discounts and negotiated rates
- Provider and deployment (OpenAI, Anthropic, Google, self-hosted)

**Conceptual Example** (illustrative only):

For a hypothetical scenario with 10,000 traces/day and 6 analysis themes:

- **Without theme_relevance filtering**: ~60K LLM calls/day (10K traces × 6 themes)
- **With theme_relevance filtering**: ~15-20K LLM calls/day (50-70% cost reduction)
  - Many traces filtered as not relevant to specific themes
  - Embeddings only created for relevant traces

**Key Cost Factors**:

1. **HogQL filtering** (pre-filters): Free/negligible - runs in ClickHouse
2. **LLM summarization calls**: Highest cost component - scales with trace count × themes
3. **theme_relevance filtering**: Reduces embedding costs by 50-90% by skipping irrelevant traces
4. **Vector embeddings**: Lower cost than LLM calls - only for relevant traces
5. **Clustering LLM calls**: Low cost - only runs once per cluster per day

**Optimization levers**:

- Tighter HogQL filters reduce traces analyzed
- Higher theme_relevance filtering rates reduce embeddings created
- Sampling rates (10% vs 100%) for high-volume scenarios
- Choice of smaller/cheaper LLM models for summarization

Use these concepts for order-of-magnitude planning, not precise budgeting.

## Open Questions

### Technical

1. **Port TS formatters or call via API?**
    - Option A: Port to Python (more control, faster, works in backend workers)
    - Option B: Expose TS formatters as API (reuse existing code, HTTP overhead)
    - **Recommendation**: Port to Python (Phase 1), maintain parity with TS

2. **How to handle trace format evolution?**
    - Version formatters?
    - Auto-detect format and use appropriate formatter?
    - **Recommendation**: Auto-detection with fallback

3. **Storage strategy for summaries?**
    - Keep PSQL for readability in UI?
    - Move to ClickHouse for FTS and scale?
    - Both (dual-write)?
    - **Recommendation**: Dual-write in Phase 2, migrate in Phase 4

4. **Stringified trace cache implementation?**
    - Redis (fast, shared across workers, TTL support)
    - In-memory (fastest, but per-worker, no persistence)
    - Database table (persistent, slower)
    - **Recommendation**: Redis with 24h TTL for active analysis runs

5. **Theme execution strategy?**
    - Sequential (simpler, slower)
    - Parallel Temporal workers (faster, more complex)
    - Hybrid (common themes sequential, custom themes parallel)
    - **Recommendation**: Start sequential (Phase 2), add parallel (Phase 4)

6. **Batching interval?**
    - Every 10 minutes (more frequent, fresher insights)
    - Every 30 minutes (less frequent, more efficient batching)
    - Hourly (least frequent, highest batch efficiency)
    - **Recommendation**: 10 minutes for MVP, configurable per team

7. **Failure handling for batch workflows?**
    - Skip failed traces and continue (simple, some data loss)
    - Retry failed traces in next batch (more robust)
    - Dead letter queue for failed traces (most robust)
    - **Recommendation**: Skip and log for MVP (Phase 2), add retries in Phase 4

### Product

1. **What analysis themes are most valuable?**
    - Need user research / interviews
    - Start with 5 built-in: errors, UX issues, feature requests, performance, success patterns
    - Allow custom themes from day 1

2. **How much control do users want?**
    - Full control (power users) vs. templates (casual users)
    - **Recommendation**: Built-in themes by default, easy custom theme creation
    - Use familiar PostHog filtering UI (low learning curve)

3. **How to price/limit usage?**
    - LLM costs scale with traces × themes
    - Theme-filtered collection dramatically reduces costs
    - **Recommendation**: Track costs per theme, set per-team limits, show cost preview

4. **Should base_filters be required or optional?**
    - Required: Forces users to think about scope
    - Optional: More flexible, but can lead to over-analysis
    - **Recommendation**: Optional but encouraged with cost warnings

5. **Cross-theme insights UI?**
    - Show all themes for a single trace?
    - Compare clusters across themes?
    - Find traces that appear in multiple themes?
    - **Recommendation**: Start with per-theme view (Phase 3), add cross-theme (Phase 4)

6. **Default sampling rate?**
    - 100% (no sampling, highest accuracy, highest cost)
    - 10% (90% cost savings, good pattern detection)
    - 1% (99% savings, for very high volume)
    - **Recommendation**: 10% default with clear UI to change, show cost preview

7. **How to communicate sampling to users?**
    - "Analyzing 10% of traces" (clear but may worry users)
    - "Smart sampling for cost efficiency" (less clear but reassuring)
    - Show pattern detection quality metrics (best but complex)
    - **Recommendation**: Show sample rate + cost savings + reassure patterns are detected

## Timeline

| Phase   | Duration  | Dependencies                    |
| ------- | --------- | ------------------------------- |
| Phase 1 | 2-3 weeks | PR #40502 merged                |
| Phase 2 | 2-3 weeks | Phase 1 complete                |
| Phase 3 | 3-4 weeks | Phase 2 complete, design review |
| Phase 4 | TBD       | Phase 3 shipped, user feedback  |

**Total to MVP (Phase 3)**: ~8-10 weeks

## Next Steps

1. **Review this plan** with team and stakeholders
2. **Validate with users**: What analysis types do they need?
3. **Finalize Phase 1 scope** and create tickets
4. **Begin porting text formatters** from PR #40502
5. **Set up testing infrastructure** for multiple trace formats

## Resources

- **PR #40502**: Generic text formatters (foundation for Phase 1)
- **PR #40364**: Current implementation (PostHog AI-specific)
- **PostHog LLMA Docs**: https://posthog.com/docs/llm-analytics
- **Standard LLMA Properties**: See docs for events, generations, spans
