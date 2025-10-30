# LLM Traces Summarization - Generalization Architecture

## Status: Draft - For Discussion

This document describes the technical architecture for generalizing the LLM traces summarization system.

## Current Architecture (MVP)

### Data Flow

```mermaid
flowchart TD
    A[Temporal Workflow:<br/>SummarizeLLMTracesWorkflow] --> B[LLMTracesSummarizer<br/>Orchestrates entire pipeline<br/>Hard-coded to PostHog AI traces]

    B --> C[1. Collector<br/>Get traces from ClickHouse<br/>LangGraph filter HARDCODED ❌]

    C --> D[2. Stringifier<br/>PostHog AI message format<br/>HARDCODED ❌]

    D --> E[3. Generator<br/>Gemini summaries<br/>Find issues prompt]

    E --> F[4. Embedder<br/>Kafka → ClickHouse<br/>document_embeddings]

    E --> G[5. Storage<br/>PostgreSQL<br/>LLMTraceSummary table]

    F --> H[Search / Clustering<br/>On Demand]
    G --> H

    H --> I[LLMTracesSummarizerFinder<br/>Cosine similarity search]
    H --> J[KmeansClusterizer<br/>Group similar issues]
    H --> K[ClusterExplainer<br/>Generate cluster names]

    style D fill:#ffcccc
    style C fill:#ffcccc
```

### Key Components

#### 1. Trace Collection (`tools/get_traces.py`)

```python
class LLMTracesSummarizerCollector:
    def get_db_traces_per_page(self, offset, date_range):
        query = TracesQuery(
            dateRange=date_range,
            properties=[
                HogQLPropertyFilter(
                    key="properties.$ai_span_name = 'LangGraph'",  # ❌ HARDCODED
                )
            ]
        )
```

#### 2. Trace Stringification (`tools/stringify_trace.py`)

```python
class LLMTracesSummarizerStringifier:
    def stringify_trace(self, trace: LLMTrace):
        messages = trace.outputState.get("messages")  # ❌ PostHog AI specific
        for message in messages:
            if message["type"] == "ai":  # ❌ PostHog AI message types
                # Format AI message
            elif message["type"] == "human":
                # Format human message
```

#### 3. Summary Generation (`tools/generate_stringified_summaries.py`)

```python
PROMPT = """
Analyze this conversation between the user and the PostHog AI assistant  # ❌ HARDCODED
List all pain points, frustrations, and feature limitations
"""

class LLMTraceSummarizerGenerator:
    async def summarize_stringified_traces(self, stringified_traces):
        # Generate summaries using Gemini
        # Cleans up LLM output (removes excessive formatting)
```

#### 4. Embedding (`tools/embed_summaries.py`)

```python
class LLMTracesSummarizerEmbedder:
    def embed_summaries(self, summarized_traces, summary_type):
        # Send to Kafka → ClickHouse document_embeddings table
        # text-embedding-3-large-3072 model
```

#### 5. Storage (`models/llm_traces_summaries.py`)

```python
class LLMTraceSummary(Model):
    team: ForeignKey
    trace_id: CharField
    summary: CharField(max_length=1000)
    trace_summary_type: CharField  # Currently only "issues_search"
```

## Proposed Generalized Architecture

### Core Principles

1. **Pluggable Stringifiers**: Abstract trace-to-text conversion
2. **Configurable Pipelines**: Users define what to analyze
3. **Extensible Summary Types**: Beyond just "issues"
4. **Backward Compatible**: Existing code continues to work

### New Data Flow

```mermaid
flowchart TD
    A[Temporal Workflow:<br/>SummarizeLLMTracesWorkflow<br/>+ TraceSummarizationConfig] --> B[LLMTracesSummarizer<br/>+ config: TraceSummarizationConfig<br/>+ Stringifier factory pattern]

    B --> C[1. Collector<br/>User-defined filters ✅]

    C --> D{2. Stringifier<br/>PLUGGABLE ✅}

    D -->|Generic LLMA| D1[GenericLLMAStringifier<br/>Standard LLMA properties]
    D -->|PostHog AI| D2[PostHogAIStringifier<br/>PostHog AI format]
    D -->|Custom| D3[CustomStringifier<br/>User-provided]

    D1 --> E[3. Generator<br/>Custom prompt per config ✅]
    D2 --> E
    D3 --> E

    E --> F[4. Embedder<br/>unchanged]

    E --> G1[5a. Storage: PSQL<br/>UI display, readability]
    E --> G2[5b. Storage: ClickHouse<br/>FTS, scale Phase 4]

    F --> H[Search / Clustering<br/>On Demand]
    G1 --> H

    style D fill:#ccffcc
    style D1 fill:#e6ffe6
    style D2 fill:#e6ffe6
    style D3 fill:#e6ffe6
    style C fill:#ccffcc
    style E fill:#ccffcc
```

## Analysis Themes: Multi-Dimensional Architecture

### Core Concept

Instead of running a single analysis pass over all traces, **Analysis Themes** provide different analytical lenses:

```python
# One trace can be analyzed by multiple themes
trace_123 = {
    "unhappy_users": "User frustrated by confusing checkout flow",
    "errors_and_failures": "Payment API timeout after 30s",
    "feature_gaps": "User requested Apple Pay support",
    "performance_cost_hotspots": "Checkout took 3.2s (2x average, 8000 tokens)",
    "happy_users": null  # Had errors, so not applicable
}
```

### Theme Architecture

```mermaid
flowchart TD
    A[User Configures Themes] --> B{Theme: Errors & Failures}
    A --> C{Theme: Unhappy Users}
    A --> D{Theme: Feature Gaps}

    B --> B1[Base Filters:<br/>none all traces]
    B --> B2[+ Theme Filters:<br/>$ai_error IS SET]
    B1 --> B3[Collect ~500 traces]
    B2 --> B3

    C --> C1[Base Filters:<br/>none all traces]
    C --> C2[+ Theme Filters:<br/>none analyze all]
    C1 --> C3[Collect ~5000 traces]
    C2 --> C3

    D --> D1[Base Filters:<br/>none all traces]
    D --> D2[+ Theme Filters:<br/>$ai_input ILIKE 'can you']
    D1 --> D3[Collect ~1500 traces]
    D2 --> D3

    B3 --> E[Stringify Cache]
    C3 --> E
    D3 --> E

    E --> F1[Error Summaries]
    E --> F2[Unhappy User Summaries]
    E --> F3[Feature Gap Summaries]

    F1 --> G1[Error Embeddings<br/>rendering='llm_traces_summary_errors_and_failures']
    F2 --> G2[Unhappy Embeddings<br/>rendering='llm_traces_summary_unhappy_users']
    F3 --> G3[Feature Embeddings<br/>rendering='llm_traces_summary_feature_gaps']

    G1 --> H1[Error Clusters]
    G2 --> H2[Unhappy User Clusters]
    G3 --> H3[Feature Gap Clusters]

    style E fill:#ffffcc
    style G1 fill:#ccffcc
    style G2 fill:#ccffcc
    style G3 fill:#ccffcc
```

### Key Benefits

1. **Efficiency**: Only collect relevant traces per theme (70%+ cost reduction)
2. **Quality**: Theme-specific prompts extract better insights
3. **Separation**: Each theme has independent embeddings/clusters
4. **Caching**: Stringified traces reused across themes
5. **Parallelism**: Themes can run in separate Temporal workers

### Cost Comparison

**Naive Approach** (collect all, analyze all):

```text
10,000 traces × 5 themes = 50,000 LLM calls + embeddings = $500
```

**Theme-Filtered Approach (with theme_relevance)**:

```text
Theme                    | HogQL Filter   | Analyzed | theme_relevant | Embedded | Cost
-------------------------|----------------|----------|----------------|----------|------
Unhappy Users            | none           | 5,000    | 1,250 (25%)   | 1,250    | $51.25
Errors & Failures        | $ai_error SET  |   500    |   400 (80%)   |   400    | $5.40
Feature Gaps             | input patterns | 1,500    |   900 (60%)   |   900    | $15.90
Performance/Cost         | latency/tokens |   500    |   350 (70%)   |   350    | $5.35
Happy Users              | no errors      | 2,000    |   800 (40%)   |   800    | $20.80
------------------------------------------------------------
Total LLM calls: 9,500 traces × $0.01 = $95
Total embeddings: 3,700 traces × $0.001 = $3.70
Total cost: $98.70 (80% savings vs naive $500 approach)
```

**Key Insight**: theme_relevance filtering reduces embedding costs by 61% (3,700 vs 9,500 traces),
while maintaining high signal-to-noise ratio in clusters.

### Two-Tier Filtering: HogQL + theme_relevance

To optimize costs and signal quality, we use a two-stage filtering strategy:

**Stage 1: HogQL Filters (Coarse, Cheap)**

- Pre-filter at query time based on properties
- Fast, deterministic filtering
- Casts wide net (some false positives acceptable)

**Stage 2: LLM theme_relevance (Fine, Expensive)**

- Post-filter after summarization using semantic understanding
- LLM returns structured output: `{"theme_relevant": true/false, "summary": "..."}`
- Only embed traces where `theme_relevant=true`
- Filters out false positives before expensive embedding/clustering

```mermaid
flowchart LR
    A[10,000 traces] --> B[HogQL Filter<br/>Coarse]
    B --> C[1,500 traces<br/>$15 cost]
    C --> D[LLM Summarize<br/>+ theme_relevance]
    D --> E{theme_relevant?}
    E -->|true 60%| F[900 traces<br/>Embed $0.90]
    E -->|false 40%| G[600 traces<br/>Skip]
    F --> H[Clustering]

    style B fill:#ffffcc
    style D fill:#ffcccc
    style F fill:#ccffcc
    style G fill:#ffeeee
```

**Benefits:**

- **Cost savings**: Only embed relevant traces (50-90% reduction)
- **Quality**: Higher signal-to-noise ratio in clusters
- **Metrics**: Relevance rate per theme useful for tuning filters
- **Universal**: Works across all theme types

**Example - Unhappy Users Theme:**

```text
Stage 1 (HogQL): No filter → 5000 traces analyzed
Stage 2 (LLM):   theme_relevant=true → 1250 traces (25% relevance rate)
Result:          Embed 1250 traces instead of 5000 (75% cost savings)
```

### Component Designs

#### 1. Analysis Theme Configuration

```python
# ee/hogai/llm_traces_summaries/config.py

from dataclasses import dataclass
from enum import Enum
from posthog.schema import HogQLPropertyFilter, DateRange

class StringifierType(str, Enum):
    """Available trace stringifiers"""
    GENERIC_LLMA = "generic_llma"      # Standard LLMA properties
    POSTHOG_AI = "posthog_ai"          # PostHog AI chat format
    CUSTOM = "custom"                  # User-provided stringifier

@dataclass
class ClusteringConfig:
    """Configuration for clustering step"""
    enabled: bool = True
    min_traces_per_cluster: int = 25
    max_traces_per_cluster: int = 100
    cosine_similarity_threshold: float = 0.72
    max_recursions: int = 3

@dataclass
class ThemeSummaryResult:
    """Result from theme-specific trace summarization"""
    theme_relevant: bool          # LLM's binary relevance assessment
    summary: str                  # Detailed explanation or "Not relevant to {theme}"

@dataclass
class AnalysisTheme:
    """
    Configuration for an analysis theme.

    A theme defines a specific analytical perspective to apply to traces.
    Each theme collects its own subset of traces and generates independent summaries.
    """

    # Identification
    theme_id: str                      # Unique ID (e.g., "payment_errors")
    name: str                          # Display name (e.g., "Payment Errors")
    description: str                   # User-facing description

    # Collection: Two-tier filtering for efficiency
    base_filters: list[HogQLPropertyFilter]    # Applied first (e.g., "checkout traces")
    theme_filters: list[HogQLPropertyFilter]   # Applied second (e.g., "has error")
    date_range: DateRange

    # Sampling: Cost control via random sampling
    sample_rate: float = 1.0           # 0.0 to 1.0 (0% to 100% of traces)
    sample_seed: int = 42              # For reproducible sampling

    # Stringification
    stringifier_type: StringifierType = StringifierType.GENERIC_LLMA
    stringifier_params: dict | None = None

    # Analysis
    prompt: str                        # Theme-specific LLM prompt (must output JSON with theme_relevant)
    llm_model: str = "gemini-2.5-flash-lite-preview-09-2025"
    filter_by_relevance: bool = True   # Enable theme_relevance filtering (default: True)

    # Clustering
    clustering_config: ClusteringConfig | None = None

    # Execution
    enabled: bool = True
    max_traces: int | None = None      # Limit for testing
    batch_size: int = 100              # LLM batch size

# Built-in themes shipped with PostHog (5 core themes)
BUILTIN_THEMES = {
    "unhappy_users": AnalysisTheme(
        theme_id="unhappy_users",
        name="Unhappy Users",
        description="Identify frustration, pain points, and user dissatisfaction expressed in any way",
        base_filters=[],  # Apply to all traces
        theme_filters=[],  # No filters - analyze all traces for signs of unhappiness
        date_range=DateRange(date_from="-7d"),
        sample_rate=1.0,  # Analyze all traces (broad perspective)
        max_traces=5000,
        filter_by_relevance=True,
        prompt="""
Analyze this trace for any signs of user frustration, dissatisfaction, or pain points.

Look for:
- Explicit complaints or negative sentiment
- Confusion, difficulty, or struggle completing tasks
- Repeated failed attempts or errors
- User expressing disappointment or unmet expectations
- Any indication the user is having a poor experience

Return ONLY valid JSON with no additional text:
{
  "theme_relevant": true/false,
  "summary": "detailed explanation of unhappiness OR 'Not relevant to Unhappy Users'"
}

Set theme_relevant=true ONLY if there are clear signs of user dissatisfaction.
If theme_relevant=false, summary should be exactly: "Not relevant to Unhappy Users"
If theme_relevant=true, explain what the user is struggling with in maximum 10 sentences.
"""
    ),

    "errors_and_failures": AnalysisTheme(
        theme_id="errors_and_failures",
        name="Errors and Failures",
        description="Surface technical errors, exceptions, and failure modes in your LLM application",
        base_filters=[],
        theme_filters=[
            HogQLPropertyFilter(
                key="properties.$ai_error IS NOT NULL OR properties.$ai_exception IS NOT NULL",
                type="hogql"
            )
        ],
        date_range=DateRange(date_from="-7d"),
        sample_rate=1.0,
        max_traces=5000,
        filter_by_relevance=True,
        prompt="""
Analyze this trace for technical errors, failures, and exceptions.

For each issue found, identify:
- What went wrong technically (error type, failure mode)
- Root cause if apparent from the trace
- Impact on the user experience
- Any patterns or context around the failure

Return ONLY valid JSON with no additional text:
{
  "theme_relevant": true/false,
  "summary": "detailed error explanation OR 'Not relevant to Errors and Failures'"
}

Set theme_relevant=true ONLY if there are actual technical errors or failures.
If theme_relevant=false, summary should be exactly: "Not relevant to Errors and Failures"
If theme_relevant=true, explain the error in maximum 10 sentences.
"""
    ),

    "feature_gaps": AnalysisTheme(
        theme_id="feature_gaps",
        name="Feature Gaps",
        description="Discover where users ask for capabilities your application doesn't support",
        base_filters=[],
        theme_filters=[
            HogQLPropertyFilter(
                key="properties.$ai_input ILIKE '%can you%' OR properties.$ai_input ILIKE '%is it possible%' OR properties.$ai_input ILIKE '%would be great%' OR properties.$ai_input ILIKE '%wish%' OR properties.$ai_input ILIKE '%need%'",
                type="hogql"
            )
        ],
        date_range=DateRange(date_from="-7d"),
        sample_rate=1.0,
        max_traces=5000,
        filter_by_relevance=True,
        prompt="""
Extract any feature requests, capability gaps, or unmet user needs from this trace.

Focus on:
- Explicit feature requests ("I need X", "Can you do Y")
- Implied needs (user trying to accomplish something the app can't do)
- Workaround attempts (user struggling due to missing feature)
- Enhancement suggestions from the user

Return ONLY valid JSON with no additional text:
{
  "theme_relevant": true/false,
  "summary": "detailed feature gap explanation OR 'Not relevant to Feature Gaps'"
}

Set theme_relevant=true ONLY if the user is requesting missing capabilities or encountering feature limitations.
If theme_relevant=false, summary should be exactly: "Not relevant to Feature Gaps"
If theme_relevant=true, explain what capability the user needs in maximum 10 sentences.
"""
    ),

    "performance_cost_hotspots": AnalysisTheme(
        theme_id="performance_cost_hotspots",
        name="Performance/Cost Hotspots",
        description="Identify high latency, expensive operations, and optimization opportunities",
        base_filters=[],
        theme_filters=[
            HogQLPropertyFilter(
                key="properties.$ai_latency_ms > 2000 OR properties.$ai_total_tokens > 5000 OR properties.$ai_cost_usd > 0.10",
                type="hogql"
            )
        ],
        date_range=DateRange(date_from="-7d"),
        sample_rate=1.0,
        max_traces=5000,
        filter_by_relevance=True,
        prompt="""
Analyze this trace for performance problems and cost drivers.

Look for:
- High latency (slow responses, long processing times)
- Excessive token usage (verbose outputs, over-contextualization)
- Expensive operations (high cost per interaction)
- Inefficient patterns (retries, redundant calls, poor caching)

Return ONLY valid JSON with no additional text:
{
  "theme_relevant": true/false,
  "summary": "detailed performance/cost analysis OR 'Not relevant to Performance/Cost Hotspots'"
}

Set theme_relevant=true ONLY if there are significant performance or cost issues worth optimizing.
If theme_relevant=false, summary should be exactly: "Not relevant to Performance/Cost Hotspots"
If theme_relevant=true, explain the issue and optimization opportunities in maximum 10 sentences.
"""
    ),

    "happy_users": AnalysisTheme(
        theme_id="happy_users",
        name="Happy Users",
        description="Identify success patterns, satisfaction signals, and what's working well",
        base_filters=[],
        theme_filters=[
            HogQLPropertyFilter(
                key="properties.$ai_error IS NULL",
                type="hogql"
            )
        ],
        date_range=DateRange(date_from="-7d"),
        sample_rate=1.0,
        max_traces=5000,
        filter_by_relevance=True,
        prompt="""
Identify what's working well in this trace and any signs of user satisfaction.

Look for:
- Successful task completion
- Positive sentiment or appreciation
- Smooth user experience without friction
- Features working as expected
- User achieving their goal efficiently

Return ONLY valid JSON with no additional text:
{
  "theme_relevant": true/false,
  "summary": "detailed success pattern explanation OR 'Not relevant to Happy Users'"
}

Set theme_relevant=true ONLY if there are clear signs of user satisfaction or success.
If theme_relevant=false, summary should be exactly: "Not relevant to Happy Users"
If theme_relevant=true, explain what made the experience successful in maximum 10 sentences.
"""
    ),
}
```

#### 2. Stringifier Interface

```python
# ee/hogai/llm_traces_summaries/tools/base_stringify.py

from abc import ABC, abstractmethod
from posthog.schema import LLMTrace

class BaseStringifier(ABC):
    """Base class for trace stringifiers"""

    @abstractmethod
    def stringify_trace(self, trace: LLMTrace) -> str | None:
        """
        Convert a trace to text representation.

        Returns:
            str: Text representation suitable for LLM summarization
            None: If trace should be skipped (e.g., no content)
        """
        pass

    @abstractmethod
    def validate_trace(self, trace: LLMTrace) -> bool:
        """Check if this stringifier can handle this trace"""
        pass
```

#### 3. Generic LLMA Stringifier

```python
# ee/hogai/llm_traces_summaries/tools/generic_stringify_trace.py

class GenericLLMAStringifier(BaseStringifier):
    """
    Generic stringifier for standard LLMA traces.
    Based on formatters from PR #40502.
    """

    def stringify_trace(self, trace: LLMTrace) -> str | None:
        lines = []

        # Trace metadata
        lines.append(self._format_trace_header(trace))

        # Process each event in the trace
        for event in trace.events:
            if event.event == "$ai_generation":
                lines.extend(self._format_generation(event))
            elif event.event == "$ai_span":
                lines.extend(self._format_span(event))

        return "\n".join(lines) if lines else None

    def _format_generation(self, event: LLMTraceEvent) -> list[str]:
        """Format a generation event"""
        lines = []
        props = event.properties

        # Input messages
        if props.get("$ai_input"):
            lines.append("\n" + "="*80)
            lines.append("INPUT:")
            lines.append(self._format_messages(props["$ai_input"]))

        # Output messages
        if props.get("$ai_output") or props.get("$ai_output_choices"):
            lines.append("\n" + "="*80)
            lines.append("OUTPUT:")
            output = props.get("$ai_output_choices") or props.get("$ai_output")
            lines.append(self._format_messages(output))

        # Tools
        if props.get("$ai_tools"):
            lines.append("\nTools available:")
            for tool in props["$ai_tools"]:
                name = tool.get("name", "unknown")
                lines.append(f"  - {name}")

        # Errors
        if props.get("$ai_error"):
            lines.append("\nERROR:")
            lines.append(str(props["$ai_error"]))

        return lines

    def _format_messages(self, messages: any) -> str:
        """Format input/output messages (OpenAI, Anthropic, LangChain formats)"""
        if isinstance(messages, str):
            return messages

        if isinstance(messages, list):
            formatted = []
            for msg in messages:
                # Handle OpenAI format: {role: "user", content: "..."}
                if isinstance(msg, dict):
                    role = msg.get("role", msg.get("type", "unknown")).upper()
                    content = msg.get("content", "")

                    # Extract text from content (handle Anthropic format)
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                                elif block.get("type") == "tool_use":
                                    text_parts.append(f"[Tool: {block.get('name')}]")
                        content = "\n".join(text_parts)

                    formatted.append(f"[{role}] {content}")

                    # Tool calls
                    if msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            name = tc.get("function", {}).get("name") or tc.get("name")
                            formatted.append(f"  Tool call: {name}")

            return "\n".join(formatted)

        # Fallback for unknown format
        return str(messages)

    def _format_span(self, event: LLMTraceEvent) -> list[str]:
        """Format a span event"""
        lines = []
        props = event.properties

        span_name = props.get("$ai_span_name", "span")
        lines.append(f"\n[{span_name.upper()}]")

        if props.get("$ai_input_state"):
            lines.append("Input state:")
            lines.append(str(props["$ai_input_state"])[:500])

        if props.get("$ai_output_state"):
            lines.append("Output state:")
            lines.append(str(props["$ai_output_state"])[:500])

        if props.get("$ai_error"):
            lines.append(f"ERROR: {props['$ai_error']}")

        return lines

    def validate_trace(self, trace: LLMTrace) -> bool:
        """Check if trace has standard LLMA events"""
        if not trace.events:
            return False

        # Must have at least one generation or span event
        for event in trace.events:
            if event.event in ("$ai_generation", "$ai_span"):
                return True

        return False
```

#### 4. PostHog AI Stringifier (Existing, Renamed)

```python
# ee/hogai/llm_traces_summaries/tools/posthog_ai_stringify_trace.py

class PostHogAIStringifier(BaseStringifier):
    """
    Stringifier for PostHog AI chat traces.
    This is the existing LLMTracesSummarizerStringifier, renamed.
    """

    def stringify_trace(self, trace: LLMTrace) -> str | None:
        # Existing implementation from stringify_trace.py
        messages = trace.outputState.get("messages")
        if not messages:
            return None

        # ... existing logic ...

    def validate_trace(self, trace: LLMTrace) -> bool:
        """Check if trace has PostHog AI structure"""
        return (
            trace.outputState is not None
            and isinstance(trace.outputState.get("messages"), list)
        )
```

#### 5. Stringifier Factory

```python
# ee/hogai/llm_traces_summaries/tools/stringify_factory.py

class StringifierFactory:
    """Factory for creating trace stringifiers"""

    @staticmethod
    def create(
        stringifier_type: StringifierType,
        team: Team,
        params: dict | None = None
    ) -> BaseStringifier:
        """Create a stringifier based on type"""

        if stringifier_type == StringifierType.GENERIC_LLMA:
            return GenericLLMAStringifier(team=team)

        elif stringifier_type == StringifierType.POSTHOG_AI:
            return PostHogAIStringifier(team=team)

        elif stringifier_type == StringifierType.CUSTOM:
            # Load custom stringifier from params
            if not params or "stringifier_class" not in params:
                raise ValueError("Custom stringifier requires stringifier_class in params")

            stringifier_class = params["stringifier_class"]
            return stringifier_class(team=team, **params.get("kwargs", {}))

        else:
            raise ValueError(f"Unknown stringifier type: {stringifier_type}")

    @staticmethod
    def auto_detect(trace: LLMTrace, team: Team) -> BaseStringifier:
        """Auto-detect best stringifier for a trace"""

        # Try PostHog AI first (most specific)
        posthog_ai = PostHogAIStringifier(team=team)
        if posthog_ai.validate_trace(trace):
            return posthog_ai

        # Fall back to generic LLMA
        generic = GenericLLMAStringifier(team=team)
        if generic.validate_trace(trace):
            return generic

        # No suitable stringifier found
        raise ValueError("No stringifier can handle this trace format")
```

#### 6. Theme-Based Collection with Caching

```python
# ee/hogai/llm_traces_summaries/tools/theme_collector.py

from typing import Dict
import redis
import json

class ThemeBasedCollector:
    """
    Collects traces for a specific theme with intelligent caching.

    Key features:
    - Combines base + theme filters for efficient collection
    - Caches stringified traces to avoid duplication
    - Returns cached text if available
    """

    def __init__(
        self,
        team: Team,
        theme: AnalysisTheme,
        stringifier: BaseStringifier,
        cache: redis.Redis
    ):
        self._team = team
        self._theme = theme
        self._stringifier = stringifier
        self._cache = cache
        self._cache_ttl = 86400  # 24 hours

    def _get_cache_key(self, trace_id: str) -> str:
        """Generate cache key for stringified trace"""
        # Include stringifier type in key (different stringifiers = different output)
        return f"trace_text:{self._team.id}:{self._theme.stringifier_type}:{trace_id}"

    def collect_and_stringify(self) -> Dict[str, str]:
        """
        Collect traces for this theme and return stringified results.
        Uses cache to avoid re-stringifying existing traces.

        Returns:
            Dict[trace_id, stringified_text]
        """
        # Combine base + theme filters
        combined_filters = self._theme.base_filters + self._theme.theme_filters

        # Collect traces from ClickHouse
        collector = LLMTracesSummarizerCollector(
            team=self._team,
            filters=combined_filters
        )

        stringified_traces = {}
        cache_hits = 0
        cache_misses = 0
        offset = 0

        while True:
            response = collector.get_db_traces_per_page(
                offset=offset,
                date_range=self._theme.date_range
            )

            # Apply sampling if configured
            traces_to_process = response.results
            if self._theme.sample_rate < 1.0:
                traces_to_process = self._sample_traces(traces_to_process)

            for trace in traces_to_process:
                cache_key = self._get_cache_key(trace.id)

                # Try cache first
                cached_text = self._cache.get(cache_key)
                if cached_text:
                    stringified_traces[trace.id] = cached_text.decode('utf-8')
                    cache_hits += 1
                else:
                    # Cache miss - stringify and store
                    try:
                        stringified = self._stringifier.stringify_trace(trace)
                        if stringified:
                            stringified_traces[trace.id] = stringified
                            # Store in cache with TTL
                            self._cache.setex(
                                cache_key,
                                self._cache_ttl,
                                stringified.encode('utf-8')
                            )
                            cache_misses += 1
                    except Exception as e:
                        # Skip failed traces, log warning
                        logger.warning(
                            f"Failed to stringify trace {trace.id} for theme "
                            f"{self._theme.theme_id}: {e}"
                        )
                        continue

            if not response.hasMore:
                break
            offset += len(response.results)

        # Log cache performance
        total = cache_hits + cache_misses
        if total > 0:
            hit_rate = (cache_hits / total) * 100
            sample_info = f", sampled at {self._theme.sample_rate * 100}%" if self._theme.sample_rate < 1.0 else ""
            logger.info(
                f"Theme {self._theme.theme_id}: Collected {total} traces{sample_info}, "
                f"cache hit rate: {hit_rate:.1f}% ({cache_hits}/{total})"
            )

        return stringified_traces

    def _sample_traces(self, traces: list[LLMTrace]) -> list[LLMTrace]:
        """Apply deterministic random sampling to traces"""
        import random
        random.seed(self._theme.sample_seed)
        sample_size = int(len(traces) * self._theme.sample_rate)
        if sample_size == 0:
            return []
        return random.sample(traces, k=min(sample_size, len(traces)))
```

#### 7. Updated Summarizer (Theme-Based)

```python
# ee/hogai/llm_traces_summaries/summarize_traces.py

class LLMTracesSummarizer:
    """
    Theme-based trace summarizer.

    Instead of analyzing all traces with one config, this orchestrates
    multiple theme analyses in parallel.
    """

    def __init__(
        self,
        team: Team,
        themes: list[AnalysisTheme],
        cache: redis.Redis
    ):
        self._team = team
        self._themes = themes
        self._cache = cache

    async def summarize_all_themes(self, date_range: DateRange):
        """
        Run analysis for all enabled themes.

        For efficiency:
        - Each theme collects only its filtered traces
        - Stringified traces are cached (shared across themes)
        - Themes can run in parallel (future: separate Temporal workers)

        Returns:
            Dict[theme_id, ThemeResults]
        """
        results = {}

        # For now, run themes sequentially (Phase 2)
        # Phase 4: Run in parallel via separate Temporal workers
        for theme in self._themes:
            if not theme.enabled:
                continue

            logger.info(f"Analyzing theme: {theme.theme_id}")
            theme_results = await self._analyze_theme(theme, date_range)
            results[theme.theme_id] = theme_results

        return results

    async def _analyze_theme(
        self,
        theme: AnalysisTheme,
        date_range: DateRange
    ) -> Dict:
        """Analyze traces for a single theme"""

        # 1. Create stringifier for this theme
        stringifier = StringifierFactory.create(
            stringifier_type=theme.stringifier_type,
            team=self._team,
            params=theme.stringifier_params
        )

        # 2. Collect and stringify traces (with caching)
        collector = ThemeBasedCollector(
            team=self._team,
            theme=theme,
            stringifier=stringifier,
            cache=self._cache
        )
        stringified_traces = await database_sync_to_async(
            collector.collect_and_stringify
        )()

        logger.info(
            f"Theme {theme.theme_id}: Collected {len(stringified_traces)} traces"
        )

        if not stringified_traces:
            return {"traces_analyzed": 0, "summaries_generated": 0}

        # 3. Generate summaries using theme-specific prompt
        generator = LLMTraceSummarizerGenerator(
            team=self._team,
            theme_id=theme.theme_id,  # ← New: theme_id for storage
            prompt=theme.prompt,
            model=theme.llm_model
        )
        summaries = await generator.summarize_stringified_traces(stringified_traces)

        # 4. Store summaries with theme_id
        await database_sync_to_async(generator.store_summaries_in_db)(summaries)

        # 5. Embed summaries with theme-scoped rendering
        embedder = LLMTracesSummarizerEmbedder(team=self._team)
        embedder.embed_summaries(
            summarized_traces=summaries,
            theme_id=theme.theme_id,  # ← New: theme-scoped embeddings
            rendering=f"llm_traces_summary_{theme.theme_id}"
        )

        # 6. Optional: Cluster if configured
        cluster_results = None
        if theme.clustering_config and theme.clustering_config.enabled:
            clusterizer = KmeansClusterizer(
                team=self._team,
                theme_id=theme.theme_id,
                config=theme.clustering_config
            )
            cluster_results = await clusterizer.cluster_summaries(summaries)

        return {
            "traces_analyzed": len(stringified_traces),
            "summaries_generated": len(summaries),
            "clusters": cluster_results
        }

    @staticmethod
    def get_default_themes() -> list[AnalysisTheme]:
        """Get default PostHog AI theme for backward compatibility"""
        return [
            AnalysisTheme(
                theme_id="posthog_ai_issues",
                name="PostHog AI Issues",
                description="Issues from PostHog AI chat",
                base_filters=[
                    HogQLPropertyFilter(
                        key="properties.$ai_span_name = 'LangGraph'",
                        type="hogql"
                    )
                ],
                theme_filters=[],
                date_range=DateRange(date_from="-7d"),
                stringifier_type=StringifierType.POSTHOG_AI,
                prompt="""
Analyze this conversation and list all pain points, frustrations, and feature limitations.
If no issues - return only "No issues found".
Provide output as plain English text in maximum 10 sentences.
"""
            )
        ]
```

#### 8. Batching Strategy: Temporal Workflow

**Approach:** Run analysis in scheduled batches (every 10 minutes) rather than real-time.

**Benefits:**

- Cost efficient (batch LLM calls)
- Predictable load on infrastructure
- Allows graceful failure handling
- Can optimize for off-peak processing

```python
# ee/hogai/llm_traces_summaries/workflows/batch_analyze_themes.py

from temporalio import workflow
from datetime import timedelta

@workflow.defn
class BatchAnalyzeThemesWorkflow:
    """
    Temporal workflow that runs every 10 minutes to analyze traces for all themes.

    This batched approach:
    - Collects traces from last 10 minutes
    - Analyzes all enabled themes
    - Handles failures gracefully (skips failed traces)
    - Batches LLM calls for efficiency
    """

    @workflow.run
    async def run(self, team_id: int):
        # Get date range: last 10 minutes
        now = datetime.now()
        date_range = DateRange(
            date_from=(now - timedelta(minutes=10)).isoformat(),
            date_to=now.isoformat()
        )

        # Get all enabled themes for this team
        themes = await workflow.execute_activity(
            get_enabled_themes,
            team_id=team_id,
            start_to_close_timeout=timedelta(seconds=30)
        )

        logger.info(f"Analyzing {len(themes)} themes for team {team_id}")

        # Analyze each theme
        for theme in themes:
            try:
                await workflow.execute_activity(
                    analyze_theme,
                    team_id=team_id,
                    theme_config=theme,
                    date_range=date_range,
                    start_to_close_timeout=timedelta(minutes=5)
                )
            except Exception as e:
                # Log error but continue with other themes
                logger.error(f"Failed to analyze theme {theme.theme_id}: {e}")
                continue

        logger.info(f"Completed batch analysis for team {team_id}")


@activity.defn
async def analyze_theme(team_id: int, theme_config: dict, date_range: DateRange):
    """
    Activity to analyze a single theme.

    Steps:
    1. Collect and stringify traces (with caching + sampling)
    2. Batch summarize (100 traces at a time to LLM)
    3. Store summaries as $ai_trace_summary events
    4. Batch embed summaries (send to Kafka)
    """
    team = Team.objects.get(id=team_id)
    theme = AnalysisTheme(**theme_config)
    cache = redis.Redis(...)  # Redis connection for caching

    # 1. Collect traces
    collector = ThemeBasedCollector(team=team, theme=theme, cache=cache)
    stringified_traces = collector.collect_and_stringify()

    if not stringified_traces:
        logger.info(f"No traces to analyze for theme {theme.theme_id}")
        return

    logger.info(f"Collected {len(stringified_traces)} traces for theme {theme.theme_id}")

    # 2. Batch summarize (100 at a time)
    summaries = {}
    batch_size = theme.batch_size  # e.g., 100
    trace_items = list(stringified_traces.items())

    for i in range(0, len(trace_items), batch_size):
        batch = dict(trace_items[i:i + batch_size])
        try:
            batch_summaries = await generate_summaries_batch(
                stringified_traces=batch,
                prompt=theme.prompt,
                model=theme.llm_model
            )
            summaries.update(batch_summaries)
        except Exception as e:
            logger.error(f"Failed to summarize batch {i}-{i+batch_size}: {e}")
            # Continue with next batch

    logger.info(f"Generated {len(summaries)} summaries for theme {theme.theme_id}")

    # 3. Store as $ai_trace_summary events
    store_summary_events(
        team=team,
        theme_id=theme.theme_id,
        summaries=summaries
    )

    # 4. Batch embed summaries
    embed_summaries_batch(
        team=team,
        theme_id=theme.theme_id,
        summaries=summaries
    )


def store_summary_events(team: Team, theme_id: str, summaries: dict):
    """Store summaries as PostHog events"""
    events = []
    for trace_id, summary_text in summaries.items():
        events.append({
            "event": "$ai_trace_summary",
            "distinct_id": "system",
            "properties": {
                "$trace_id": trace_id,
                "$analysis_theme_id": theme_id,
                "$summary": summary_text,
                "$summary_metadata": {
                    "timestamp": datetime.now().isoformat()
                }
            }
        })

    # Batch ingest events
    capture_events(team=team, events=events)


def embed_summaries_batch(team: Team, theme_id: str, summaries: dict):
    """Send summaries to Kafka for embedding"""
    embedder = LLMTracesSummarizerEmbedder(team=team)

    for trace_id, summary_text in summaries.items():
        try:
            embedder.embed_summary(
                content=summary_text,
                document_id=trace_id,
                rendering=f"llm_traces_summary_{theme_id}"
            )
        except Exception as e:
            # Skip failed embeddings
            logger.warning(f"Failed to embed summary for trace {trace_id}: {e}")
            continue
```

**Scheduling:**

```python
# Schedule workflow to run every 10 minutes for each team
schedule = workflow.schedule(
    id=f"batch-analyze-themes-team-{team_id}",
    workflow=BatchAnalyzeThemesWorkflow,
    args=[team_id],
    cron="*/10 * * * *",  # Every 10 minutes
)
```

#### 9. Clustering: Theme-Based Issue Discovery

**Overview**

Clustering groups similar summaries together to identify common patterns, issues, and trends. In the theme-based architecture, each theme gets its own independent clustering:

- **Error Analysis Theme** → Clusters of similar errors
- **UX Issues Theme** → Clusters of similar UX problems
- **Feature Requests Theme** → Clusters of similar feature requests

**Trigger: Scheduled Only (Keep It Simple)**

```python
# Daily at 3 AM UTC:
# - For each enabled theme with clustering enabled
# - Dynamically fetch embeddings (expand date range until min_n_traces met)
# - Run KMeans clustering
# - Generate cluster names + descriptions via LLM (one call per cluster)
# - Store as $ai_trace_cluster events
```

**Dynamic Date Range (Handle Low-Volume Teams)**

Not all teams have high trace volume. We dynamically expand the date range to ensure we have enough data:

```python
# Configuration
min_n_traces = 100   # Minimum for meaningful clustering
max_n_traces = 5000  # Cap to prevent OOM
max_n_days = 30      # Don't look back too far (data gets stale)

# Algorithm: Try progressively larger windows
days_to_try = [3, 7, 14, 30]

for days in days_to_try:
    traces = fetch_embeddings(theme, days, limit=max_n_traces)

    if len(traces) >= min_n_traces:
        # Success! We have enough data
        return cluster_theme(traces, actual_days=days)

    if days >= max_n_days:
        # Exhausted search window - skip clustering
        logger.info(
            f"Not enough traces for theme {theme.theme_id}: "
            f"{len(traces)} < {min_n_traces} (searched {max_n_days} days)"
        )
        return None  # No clustering result
```

**Example Scenarios:**

| Team Volume       | 3 days | 7 days | 14 days | 30 days | Outcome                         |
| ----------------- | ------ | ------ | ------- | ------- | ------------------------------- |
| High (PostHog AI) | 5000+  | -      | -       | -       | ✅ Cluster 5000 traces (3 days) |
| Medium            | 50     | 150    | -       | -       | ✅ Cluster 150 traces (7 days)  |
| Low               | 5      | 15     | 40      | 60      | ⚠️ Skip clustering (< 100)      |

**Key Insight: Embeddings are the Durable Asset**

Embeddings are stored permanently and reused across features:

```text
Trace → Summary → Embedding [STORED IN CLICKHOUSE]
                      ↓
                  (reusable)
                      ↓
    ┌─────────────────┼─────────────────┐
    ↓                 ↓                 ↓
Clustering    Similarity Search    Future Features
```

Clustering just reads and groups existing embeddings. It's ephemeral - a means to surface insights.

**Cluster Storage: `$ai_trace_cluster` Events**

Following the `$ai_trace_summary` pattern, clusters are stored as PostHog events:

```python
# Regular cluster event
{
    "event": "$ai_trace_cluster",
    "distinct_id": f"theme:{theme_id}",
    "properties": {
        # Theme identification
        "$ai_theme_id": "error_analysis",

        # Cluster identification
        "$ai_cluster_id": "cluster_0",  # Within this theme
        "$ai_clustering_run_id": "2025-10-30T03:00:00Z",  # Groups clusters from same daily run

        # LLM-generated cluster explanation
        "$ai_cluster_name": "Payment Gateway Timeout Errors",
        "$ai_cluster_description": "Users experiencing 30-second timeouts during checkout payment processing, primarily with Stripe API. Affects approximately 3% of checkout attempts, typically during peak hours.",

        # Cluster metrics
        "$ai_cluster_avg_similarity": 0.85,  # Higher = tighter cluster
        "$ai_cluster_size": 47,  # Number of traces
        "$ai_is_unclustered": false,  # Regular cluster

        # Trace references (with 5000 max cap, storing all IDs is safe)
        "$ai_trace_ids": ["trace_123", "trace_456", ...],  # All traces in cluster

        # Metadata
        "$ai_date_range_start": "2025-10-27T00:00:00Z",  # Last 3 days
        "$ai_date_range_end": "2025-10-30T00:00:00Z"
    }
}

# Special "unclustered" virtual cluster (treated as regular cluster for simplicity)
{
    "event": "$ai_trace_cluster",
    "distinct_id": f"theme:{theme_id}",
    "properties": {
        "$ai_theme_id": "error_analysis",
        "$ai_cluster_id": "unclustered",  # ← Special reserved ID
        "$ai_clustering_run_id": "2025-10-30T03:00:00Z",

        "$ai_cluster_name": "Everything Else",
        "$ai_cluster_description": "Traces that didn't fit into any cluster. May contain novel edge cases, one-off issues, or insufficient similarity to form patterns.",

        "$ai_cluster_size": 30,
        "$ai_trace_ids": ["trace_x", "trace_y", ...],

        "$ai_is_unclustered": true,  # ← Flag for special UI handling
        "$ai_cluster_avg_similarity": null  # No similarity for unclustered
    }
}
```

**Benefits of Virtual Unclustered Cluster:**

- Uniform storage (same event type, same queries)
- Versioned history (unclustered traces preserved per run)
- Simple UI code (same modal, same interactions)
- Fast queries (no computation needed)
- Complete coverage (all traces accounted for)

**Simplified Clustering Flow with Dynamic Date Range**

```python
# ee/hogai/llm_traces_summaries/tools/theme_clusterer.py

class ThemeClusterer:
    """
    Clusters summaries for a specific theme.

    Simple daily workflow:
    1. Dynamically fetch embeddings (expand date range until min threshold met)
    2. Run KMeans clustering
    3. Generate cluster names + descriptions (one LLM call per cluster)
    4. Store as $ai_trace_cluster events
    """

    # Configuration constants
    MIN_TRACES_FOR_CLUSTERING = 100
    MAX_TRACES_FOR_CLUSTERING = 5000
    MAX_DAYS_LOOKBACK = 30
    DAYS_TO_TRY = [3, 7, 14, 30]

    def __init__(self, team: Team, theme: AnalysisTheme):
        self._team = team
        self._theme = theme
        self._rendering = f"llm_traces_summary_{theme.theme_id}"

    async def cluster_theme(self) -> ClusteringResult | None:
        """
        Run daily clustering for this theme.

        Returns None if insufficient data (< MIN_TRACES_FOR_CLUSTERING).
        """

        # 1. Dynamically fetch embeddings (expand date range as needed)
        embeddings_data = await self._fetch_embeddings_dynamic()

        if not embeddings_data:
            logger.info(
                f"Insufficient traces for clustering theme {self._theme.theme_id}: "
                f"< {self.MIN_TRACES_FOR_CLUSTERING} traces in last {self.MAX_DAYS_LOOKBACK} days"
            )
            return None  # Skip clustering

        actual_days = embeddings_data["actual_days_used"]
        trace_count = len(embeddings_data["trace_ids"])

        logger.info(
            f"Clustering theme {self._theme.theme_id}: "
            f"{trace_count} traces from last {actual_days} days"
        )

        # 2. Run KMeans clustering (uses existing algorithm)
        clusters_raw, unclustered = await database_sync_to_async(
            KmeansClusterizer.clusterize_traces
        )(
            embedded_traces=embeddings_data["trace_ids"],
            embeddings=embeddings_data["vectors"],
            max_tail_size=int(len(embeddings_data["trace_ids"]) * 0.5)
        )

        # 3. Generate cluster names + descriptions (one LLM call per cluster)
        explainer = ClusterExplainer(
            model_id=self._theme.llm_model,
            groups_raw=clusters_raw,
            summaries_to_trace_ids_mapping=embeddings_data["summaries_mapping"]
        )

        explained_clusters = await database_sync_to_async(
            explainer.explain_clusters  # ← Returns {name, description} per cluster
        )()

        # 4. Store as events (including unclustered)
        unclustered_trace_ids = [t.trace_id for t in unclustered.traces]
        await self._store_cluster_events(
            explained_clusters,
            unclustered_trace_ids,
            actual_days_used=actual_days
        )

        return self._build_result(explained_clusters, unclustered)

    async def _fetch_embeddings_dynamic(self) -> dict | None:
        """
        Dynamically fetch embeddings, expanding date range until we have enough data.

        Returns:
            {
                "trace_ids": [...],
                "vectors": [...],
                "summaries_mapping": {summary_text: trace_id},
                "actual_days_used": int
            }
            OR None if insufficient data even at max lookback
        """
        for days in self.DAYS_TO_TRY:
            embeddings_data = await self._fetch_embeddings_for_days(
                days=days,
                max_traces=self.MAX_TRACES_FOR_CLUSTERING
            )

            trace_count = len(embeddings_data["trace_ids"])

            if trace_count >= self.MIN_TRACES_FOR_CLUSTERING:
                # Success! We have enough data
                embeddings_data["actual_days_used"] = days
                logger.info(
                    f"Theme {self._theme.theme_id}: Found {trace_count} traces in {days} days"
                )
                return embeddings_data

            if days >= self.MAX_DAYS_LOOKBACK:
                # Exhausted search window
                logger.info(
                    f"Theme {self._theme.theme_id}: Only {trace_count} traces in {days} days "
                    f"(need {self.MIN_TRACES_FOR_CLUSTERING})"
                )
                return None

        return None

    async def _fetch_embeddings_for_days(self, days: int, max_traces: int) -> dict:
        """
        Fetch embeddings for this theme from ClickHouse for a specific date range.

        Returns:
            {
                "trace_ids": [...],
                "vectors": [...],  # 3072-dim
                "summaries_mapping": {summary_text: trace_id}
            }
        """
        query = f"""
        SELECT
            document_id as trace_id,
            content as summary,
            vector as embedding
        FROM posthog_document_embeddings
        WHERE team_id = {self._team.id}
          AND product = 'llm_traces_summaries'
          AND rendering = '{self._rendering}'
          AND timestamp >= now() - INTERVAL {days} DAY
        ORDER BY timestamp DESC
        LIMIT {max_traces}
        """

        results = await database_sync_to_async(execute_clickhouse_query)(query)

        trace_ids = [r["trace_id"] for r in results]
        vectors = [r["embedding"] for r in results]
        summaries_mapping = {r["summary"]: r["trace_id"] for r in results}

        return {
            "trace_ids": trace_ids,
            "vectors": vectors,
            "summaries_mapping": summaries_mapping
        }

    async def _store_cluster_events(
        self,
        explained_clusters: dict,
        unclustered_traces: list[str],
        actual_days_used: int
    ):
        """Store clustering results + unclustered as events"""
        events = []
        run_id = datetime.now().isoformat()
        date_range_start = f"-{actual_days_used}d"

        # Store regular clusters
        for cluster_id, cluster_data in explained_clusters.items():
            events.append({
                "event": "$ai_trace_cluster",
                "distinct_id": f"theme:{self._theme.theme_id}",
                "properties": {
                    "$ai_theme_id": self._theme.theme_id,
                    "$ai_cluster_id": cluster_id,
                    "$ai_clustering_run_id": run_id,
                    "$ai_cluster_name": cluster_data.name,
                    "$ai_cluster_description": cluster_data.description,
                    "$ai_cluster_avg_similarity": cluster_data.avg_similarity,
                    "$ai_cluster_size": len(cluster_data.suggestions),
                    "$ai_trace_ids": [s.trace_id for s in cluster_data.suggestions],
                    "$ai_is_unclustered": false,
                    "$ai_date_range_days": actual_days_used,  # Actual days used
                    "$ai_date_range_start": date_range_start,
                    "$ai_date_range_end": "now"
                }
            })

        # Store unclustered as special virtual cluster
        if unclustered_traces:
            events.append({
                "event": "$ai_trace_cluster",
                "distinct_id": f"theme:{self._theme.theme_id}",
                "properties": {
                    "$ai_theme_id": self._theme.theme_id,
                    "$ai_cluster_id": "unclustered",
                    "$ai_clustering_run_id": run_id,
                    "$ai_cluster_name": "Everything Else",
                    "$ai_cluster_description": "Traces that didn't fit into any cluster. May contain novel edge cases, one-off issues, or insufficient similarity to form patterns.",
                    "$ai_cluster_size": len(unclustered_traces),
                    "$ai_trace_ids": unclustered_traces,
                    "$ai_is_unclustered": true,
                    "$ai_cluster_avg_similarity": null,
                    "$ai_date_range_days": actual_days_used,
                    "$ai_date_range_start": date_range_start,
                    "$ai_date_range_end": "now"
                }
            })

        await database_sync_to_async(capture_events)(team=self._team, events=events)
        logger.info(
            f"Stored {len(events)} clusters for theme {self._theme.theme_id} "
            f"({actual_days_used} days of data)"
        )
```

**Updated ClusterExplainer: Generating Name + Description**

```python
# ee/hogai/llm_traces_summaries/tools/clustering/explain_clusters.py (updated)

CLUSTER_EXPLAIN_PROMPT = """
Analyze these summaries from similar user traces:

{summaries}

Generate a concise explanation of this cluster:

1. NAME: A short title (up to 10 words) describing the common issue or pattern
   - Focus on the specific problem, product, or feature
   - Use Title Case For Each Word

2. DESCRIPTION: A 2-3 sentence explanation including:
   - What the core issue or pattern is
   - How it affects users
   - Any notable patterns (frequency, severity, context)

Return ONLY valid JSON with no additional text:
{{"name": "...", "description": "..."}}
"""

@dataclass(frozen=True)
class ExplainedClusterizedSuggestionsGroup:
    suggestions: list[ClusterizedSuggestion]
    avg_similarity: float
    cluster_label: str
    name: str          # ← LLM-generated name
    description: str   # ← LLM-generated description (NEW)

class ClusterExplainer:
    def _generate_cluster_explanation(self, summaries: list[str]) -> dict:
        """
        Generate name + description for a cluster via LLM.

        One call per cluster (Option B) for better quality.
        """
        message = CLUSTER_EXPLAIN_PROMPT.format(
            summaries=json.dumps(summaries[:5])  # First 5 summaries
        )

        response = self.client.models.generate_content(
            model=self.model_id,
            contents=message,
            config=GenerateContentConfig(temperature=0)
        )

        # Parse JSON response
        try:
            result = json.loads(response.text)
            return {
                "name": result["name"],
                "description": result["description"]
            }
        except json.JSONDecodeError:
            # Fallback if LLM doesn't return valid JSON
            logger.warning(f"Failed to parse cluster explanation: {response.text}")
            return {
                "name": response.text[:100],
                "description": "Unable to generate description"
            }

```

**Daily Clustering Workflow**

```python
# ee/hogai/llm_traces_summaries/workflows/daily_clustering.py

from temporalio import workflow
from datetime import timedelta

@workflow.defn
class DailyClusteringWorkflow:
    """
    Simple daily clustering workflow.

    Schedule: Daily at 3 AM UTC
    For each theme: Cluster last 3 days (max 5000 traces)
    """

    @workflow.run
    async def run(self, team_id: int):
        logger.info(f"Starting daily clustering for team {team_id}")

        # Get all enabled themes with clustering enabled
        themes = await workflow.execute_activity(
            get_enabled_themes,
            team_id=team_id,
            start_to_close_timeout=timedelta(seconds=30)
        )

        # Cluster each theme
        for theme in themes:
            if not theme.clustering_config or not theme.clustering_config.enabled:
                continue

            try:
                await workflow.execute_activity(
                    cluster_theme_activity,
                    team_id=team_id,
                    theme_id=theme.theme_id,
                    start_to_close_timeout=timedelta(minutes=10)
                )
            except Exception as e:
                logger.error(f"Failed to cluster theme {theme.theme_id}: {e}")
                continue


@activity.defn
async def cluster_theme_activity(team_id: int, theme_id: str):
    """Cluster a single theme"""
    team = Team.objects.get(id=team_id)
    theme_config = AnalysisThemeConfig.objects.get(team=team, theme_id=theme_id)
    theme = AnalysisTheme(**theme_config.config)

    clusterer = ThemeClusterer(team=team, theme=theme)
    await clusterer.cluster_theme()  # Fetches, clusters, stores events


# Schedule: Daily at 3 AM UTC
schedule = workflow.schedule(
    id=f"daily-clustering-team-{team_id}",
    workflow=DailyClusteringWorkflow,
    args=[team_id],
    cron="0 3 * * *"
)
```

**Querying Latest Clusters**

```python
# Fetch latest clusters for a theme
def get_latest_clusters_for_theme(team: Team, theme_id: str) -> list[dict]:
    """
    Query $ai_trace_cluster events from ClickHouse.
    Returns clusters from the most recent run.
    """
    query = f"""
    SELECT
        properties.$ai_cluster_id as cluster_id,
        properties.$ai_clustering_run_id as run_id,
        properties.$ai_cluster_name as name,
        properties.$ai_cluster_description as description,
        properties.$ai_cluster_size as size,
        properties.$ai_cluster_avg_similarity as avg_similarity,
        properties.$ai_trace_ids as trace_ids,
        timestamp
    FROM events
    WHERE team_id = {team.id}
      AND event = '$ai_trace_cluster'
      AND properties.$ai_theme_id = '{theme_id}'
    ORDER BY timestamp DESC
    LIMIT 50  # Max clusters we'd ever have
    """

    results = execute_clickhouse_query(query)

    if not results:
        return []

    # Get clusters from latest run only
    latest_run_id = results[0]["run_id"]
    return [r for r in results if r["run_id"] == latest_run_id]
```

**Key Design Decisions**

1. **Scheduled Only**: Simple daily clustering at 3 AM UTC (no on-demand for MVP)
2. **Event Storage**: `$ai_trace_cluster` events align with PostHog patterns
3. **Per-Theme Independence**: Each theme has separate clusters
4. **Embeddings as Durable Asset**: Clustering reuses existing embeddings
5. **LLM per Cluster**: One call per cluster for name + description (better quality)
6. **Hard Caps**: 3 days of data, max 5000 traces per theme (prevents OOM)
7. **Versioning**: `$ai_clustering_run_id` groups clusters from same daily run
8. **Unclustered Virtual Cluster**: Uniform storage and UI handling for unclustered traces

#### 10. Reports UI: Surfacing Cluster Insights

**Tab Structure**

```text
LLM Analytics:
├── Traces (existing - raw trace explorer)
└── Reports (NEW - cluster insights per theme)
```

**Reports Landing Page**

```text
┌─────────────────────────────────────────────────────────────┐
│ LLM Analytics > Reports                                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│ Theme Reports                                    Last 24h ▼  │
│                                                               │
│ ┌───────────────────────────────────────────────────────┐   │
│ │ Error Analysis Report                    Updated 2h ago│   │
│ │ 12 clusters • 470 traces analyzed • 94% coverage      │   │
│ │ [View Report →]                                       │   │
│ ├───────────────────────────────────────────────────────┤   │
│ │ UX Issues Report                        Updated 2h ago│   │
│ │ 24 clusters • 3,000 traces analyzed • 87% coverage    │   │
│ │ [View Report →]                                       │   │
│ ├───────────────────────────────────────────────────────┤   │
│ │ Feature Requests Report                 Updated 2h ago│   │
│ │ 8 clusters • 1,500 traces analyzed • 78% coverage     │   │
│ │ [View Report →]                                       │   │
│ └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Individual Report Detail View**

```text
┌─────────────────────────────────────────────────────────────┐
│ ← Back to Reports                                            │
│                                                               │
│ Error Analysis Report                                         │
│ Last updated: 2 hours ago • Last 3 days of data              │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│ Overview                                                      │
│ ┌──────────────┬──────────────┬──────────────┬─────────────┐│
│ │ 500 traces   │ 12 clusters  │ 94% coverage │ 30 singles  ││
│ │ analyzed     │ found        │ (470 traces) │ (6%)        ││
│ └──────────────┴──────────────┴──────────────┴─────────────┘│
│                                                               │
│ Clusters                             Sort: Size ▼  Filter... │
│                                                               │
│ ┌───────────────────────────────────────────────────────┐   │
│ │ 1. Payment Gateway Timeout Errors                     │   │
│ │    87 traces (17.4%) • Similarity: 0.85              │   │
│ │                                                       │   │
│ │    Users experiencing 30-second timeouts during      │   │
│ │    checkout payment processing, primarily with Stripe│   │
│ │    API. Affects ~3% of checkout attempts.            │   │
│ │                                                       │   │
│ │    ▼ Sample Summaries (5 shown, 87 total)           │   │
│ │    • "Stripe payment timeout after 30s, user..."     │   │
│ │    • "Payment gateway returned 504 during..."        │   │
│ │    • "Checkout failed with timeout error..."         │   │
│ │    • "API timeout on payment confirmation..."        │   │
│ │    • "30 second wait then payment failed..."         │   │
│ │                                                       │   │
│ │    [View All 87 Traces →]  [Create Alert]  [Export] │   │
│ ├───────────────────────────────────────────────────────┤   │
│ │ 2. Card Declined Errors                               │   │
│ │    65 traces (13.0%) • Similarity: 0.78              │   │
│ │    ...                                                │   │
│ ├───────────────────────────────────────────────────────┤   │
│ │ ▶ Everything Else (30 traces, 6%)                    │   │
│ │   Traces that didn't fit any cluster. May contain    │   │
│ │   novel edge cases or one-off issues.                │   │
│ │   [View All 30 Traces →]                             │   │
│ └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Key Interactions**

1. **"View All X Traces"** → Opens inline modal with paginated trace summaries
2. **Click summary** → Opens individual trace detail page
3. **Expandable clusters** → Show/hide sample summaries
4. **Sort/Filter** → By size, similarity, date
5. **Everything Else** → Collapsed by default, treated as special cluster

**Modal: View All Traces in Cluster**

```text
┌─────────────────────────────────────────────────────────────┐
│ Payment Gateway Timeout Errors - 87 Traces              × │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│ ┌───────────────────────────────────────────────────────┐   │
│ │ trace_123 • 2h ago                                    │   │
│ │ Stripe payment timeout after 30s, user abandoned cart│   │
│ │ [View Trace →]                                        │   │
│ ├───────────────────────────────────────────────────────┤   │
│ │ trace_456 • 3h ago                                    │   │
│ │ Payment gateway returned 504 during checkout          │   │
│ │ [View Trace →]                                        │   │
│ ├───────────────────────────────────────────────────────┤   │
│ │ ...                                                    │   │
│ └───────────────────────────────────────────────────────┘   │
│                                                               │
│ Showing 1-20 of 87  [Load More]                              │
└─────────────────────────────────────────────────────────────┘
```

**API Endpoints**

```python
# List all theme reports (landing page)
GET /api/projects/{team_id}/llm_traces/reports

Response:
{
  "reports": [
    {
      "theme_id": "error_analysis",
      "theme_name": "Error Analysis",
      "last_updated": "2025-10-30T01:00:00Z",
      "stats": {
        "total_traces": 500,
        "clusters_found": 12,
        "coverage_pct": 94.0
      }
    },
    ...
  ]
}

# Get detailed report for a theme
GET /api/projects/{team_id}/llm_traces/reports/{theme_id}

Response:
{
  "theme": {
    "id": "error_analysis",
    "name": "Error Analysis",
    "description": "..."
  },
  "last_updated": "2025-10-30T01:00:00Z",
  "stats": {
    "total_traces_analyzed": 500,
    "clusters_found": 12,
    "traces_clustered": 470,
    "coverage_pct": 94.0,
    "unclustered_count": 30
  },
  "clusters": [
    {
      "id": "cluster_0",
      "name": "Payment Gateway Timeout Errors",
      "description": "Users experiencing...",
      "size": 87,
      "coverage_pct": 17.4,
      "avg_similarity": 0.85,
      "is_unclustered": false,
      "sample_summaries": [
        {"trace_id": "trace_123", "summary": "..."},
        ...  // First 5
      ]
    },
    ...
    {
      "id": "unclustered",
      "name": "Everything Else",
      "description": "Traces that didn't fit...",
      "size": 30,
      "coverage_pct": 6.0,
      "avg_similarity": null,
      "is_unclustered": true,
      "sample_summaries": [...]
    }
  ]
}

# Get all summaries for traces in a cluster (for modal)
GET /api/projects/{team_id}/llm_traces/summaries?trace_ids=id1,id2&theme_id=error_analysis&limit=20&offset=0

Response:
{
  "summaries": [
    {
      "trace_id": "trace_123",
      "summary": "Stripe payment timeout after 30s...",
      "timestamp": "2025-10-30T14:23:00Z",
      "trace_url": "/project/123/llm-analytics/traces/trace_123"
    },
    ...
  ],
  "total": 87,
  "has_more": true
}
```

**Backend Implementation**

```python
# ee/api/llm_traces_reports.py

@router.get("/api/projects/{team_id}/llm_traces/reports/{theme_id}")
def get_theme_report(team_id: int, theme_id: str):
    """
    Get detailed report for a theme.

    Steps:
    1. Query latest $ai_trace_cluster events for this theme
    2. Group by clustering_run_id to get latest run
    3. Separate regular clusters vs unclustered
    4. Fetch sample summaries (first 5 trace IDs per cluster)
    5. Calculate coverage stats
    """
    team = Team.objects.get(id=team_id)

    # Fetch latest clusters
    clusters = get_latest_clusters_for_theme(team, theme_id)

    if not clusters:
        return {"error": "No clustering results found"}

    # Separate regular vs unclustered
    regular_clusters = [c for c in clusters if not c["is_unclustered"]]
    unclustered = next((c for c in clusters if c["is_unclustered"]), None)

    # Fetch sample summaries for each cluster
    for cluster in regular_clusters:
        sample_trace_ids = cluster["trace_ids"][:5]  # First 5
        cluster["sample_summaries"] = fetch_summaries(team, theme_id, sample_trace_ids)

    if unclustered:
        sample_trace_ids = unclustered["trace_ids"][:5]
        unclustered["sample_summaries"] = fetch_summaries(team, theme_id, sample_trace_ids)

    # Calculate stats
    total_traces = sum(c["size"] for c in clusters)

    return {
        "theme": get_theme_config(team, theme_id),
        "last_updated": clusters[0]["timestamp"],
        "stats": {
            "total_traces_analyzed": total_traces,
            "clusters_found": len(regular_clusters),
            "traces_clustered": sum(c["size"] for c in regular_clusters),
            "coverage_pct": (sum(c["size"] for c in regular_clusters) / total_traces * 100) if total_traces else 0,
            "unclustered_count": unclustered["size"] if unclustered else 0
        },
        "clusters": regular_clusters + ([unclustered] if unclustered else [])
    }


def fetch_summaries(team: Team, theme_id: str, trace_ids: list[str]) -> list[dict]:
    """Fetch summaries for specific trace IDs"""
    query = f"""
    SELECT
        properties.$trace_id as trace_id,
        properties.$summary as summary,
        timestamp
    FROM events
    WHERE team_id = {team.id}
      AND event = '$ai_trace_summary'
      AND properties.$analysis_theme_id = '{theme_id}'
      AND properties.$trace_id IN ({','.join(f"'{tid}'" for tid in trace_ids)})
    ORDER BY timestamp DESC
    """

    results = execute_clickhouse_query(query)

    return [
        {
            "trace_id": r["trace_id"],
            "summary": r["summary"],
            "timestamp": r["timestamp"],
            "trace_url": f"/project/{team.id}/llm-analytics/traces/{r['trace_id']}"
        }
        for r in results
    ]
```

**UI Component Structure**

```typescript
// frontend/src/scenes/llm-analytics/Reports/
├── ReportsScene.tsx              // Landing page with all theme reports
├── ThemeReportScene.tsx          // Individual theme report detail
├── ClusterCard.tsx               // Expandable cluster card
├── ViewAllTracesModal.tsx        // Modal for viewing all traces in cluster
└── types.ts                      // TypeScript types

// Example component hierarchy:
<ReportsScene>
  <ThemeReportCard theme="error_analysis" onClick={→ navigate} />
  <ThemeReportCard theme="ux_issues" onClick={→ navigate} />
</ReportsScene>

<ThemeReportScene theme="error_analysis">
  <StatsOverview stats={...} />
  <ClusterCard cluster={cluster1} expanded={false}>
    <SampleSummaries summaries={[...]} />
    <Button onClick={→ openModal}>View All Traces</Button>
  </ClusterCard>
  <ClusterCard cluster={unclusteredCluster} expanded={false} isSpecial />
</ThemeReportScene>

<ViewAllTracesModal traceIds={[...]} themeId="error_analysis">
  <TraceSummaryList summaries={[...]} pagination={...} />
</ViewAllTracesModal>
```

**Design Decisions**

1. **Inline Modal**: Simpler than modifying Traces tab, reuses existing trace detail pages
2. **First 5 Samples**: Simple, fast, no complex selection logic needed
3. **Unclustered at Bottom**: Collapsed by default, less visual clutter
4. **Uniform Treatment**: Unclustered is just another cluster with special flag
5. **Pagination**: Load 20 summaries at a time in modal
6. **Direct Links**: Each summary links to existing trace detail page

#### 11. Prompt Templates

```python
# ee/hogai/llm_traces_summaries/prompts.py

PROMPT_TEMPLATES = {
    SummaryType.ISSUES_SEARCH: """
Analyze this trace and list all pain points, frustrations, and feature limitations.
Focus on specific issues the user experienced when interacting with the system.
If no issues - return only "No issues found" without additional comments.
Provide output as plain English text in maximum 10 sentences.

{stringified_trace}
""",

    SummaryType.ERROR_ANALYSIS: """
Analyze this trace for errors, failures, and exceptions.
For each error found, identify:
- What went wrong
- Root cause if apparent
- Impact on the user experience

If no errors - return only "No errors found".
Provide output as plain English text in maximum 10 sentences.

{stringified_trace}
""",

    SummaryType.FEATURE_REQUESTS: """
Extract all feature requests, suggestions, and improvement ideas from this trace.
Focus on explicit user requests and implied needs.
If no feature requests - return only "No feature requests found".
Provide output as plain English text in maximum 10 sentences.

{stringified_trace}
""",

    SummaryType.SUCCESS_PATTERNS: """
Identify what went well in this trace.
Look for successful interactions, good UX moments, and features that worked as expected.
If nothing particularly successful - return only "No clear success patterns found".
Provide output as plain English text in maximum 10 sentences.

{stringified_trace}
""",

    SummaryType.PERFORMANCE_ISSUES: """
Analyze this trace for performance problems.
Look for high latency, excessive costs, token usage, or slow operations.
Identify bottlenecks and areas for optimization.
If no performance issues - return only "No performance issues found".
Provide output as plain English text in maximum 10 sentences.

{stringified_trace}
"""
}

def get_prompt_for_summary_type(
    summary_type: SummaryType,
    custom_prompt: str | None = None
) -> str:
    """Get prompt template for a summary type"""
    if custom_prompt:
        return custom_prompt

    return PROMPT_TEMPLATES.get(summary_type, PROMPT_TEMPLATES[SummaryType.ISSUES_SEARCH])
```

## Storage Strategy: Native PostHog Events

### Summary Storage as `$ai_trace_summary` Events

**Approach:** Store each trace summary as a PostHog event - the native PostHog pattern.

**Benefits:**

- ✅ Uses existing event ingestion pipeline
- ✅ Standard PostHog event (can query like any LLMA event)
- ✅ No new tables needed
- ✅ Scales automatically with ClickHouse
- ✅ Easy to join with traces and other events
- ✅ Supports full-text search via ClickHouse
- ✅ Can be queried using standard PostHog event queries

**Event Schema:**

```python
# Each summary is stored as an event
{
    "event": "$ai_trace_summary",
    "distinct_id": "system",
    "properties": {
        # Core identification
        "$trace_id": "trace_123",
        "$analysis_theme_id": "error_analysis",

        # Summary content
        "$summary": "Payment timeout after 30s during checkout. Stripe API returned 504 gateway timeout.",

        # Metadata
        "$summary_metadata": {
            "llm_model": "gemini-2.5-flash-lite",
            "prompt_tokens": 850,
            "completion_tokens": 45,
            "total_cost": 0.0001,
            "timestamp": "2025-01-30T12:34:56Z"
        },

        # Original trace reference
        "$original_trace_span_name": "checkout",
        "$original_trace_error_present": true,

        # Theme configuration
        "$theme_sample_rate": 0.1,  # If sampling was used
    },
    "timestamp": "2025-01-30T12:34:56Z"
}
```

**Querying Summaries:**

```python
# Get all error summaries for a date range
events = query_events(
    event="$ai_trace_summary",
    properties=[
        {"key": "$analysis_theme_id", "value": "error_analysis", "operator": "exact"}
    ],
    date_from="-7d"
)

# Join with original traces
SELECT
    summaries.properties.$trace_id as trace_id,
    summaries.properties.$summary as summary,
    traces.properties.$ai_error as error,
    traces.properties.$ai_latency_ms as latency
FROM events summaries
INNER JOIN events traces
    ON summaries.properties.$trace_id = traces.properties.$trace_id
WHERE summaries.event = '$ai_trace_summary'
  AND summaries.properties.$analysis_theme_id = 'error_analysis'
  AND traces.event = '$ai_generation'
```

**De-duplication:**

```sql
-- Use ReplacingMergeTree on (team_id, $trace_id, $analysis_theme_id)
-- Latest summary replaces old ones automatically

CREATE TABLE events (
    ...
)
ENGINE = ReplacingMergeTree(timestamp)
ORDER BY (team_id, event, properties.$trace_id, properties.$analysis_theme_id)
```

**Migration from PostgreSQL:**

```python
# Phase 1: Dual-write (PostgreSQL + ClickHouse events)
def store_summary(trace_id: str, theme_id: str, summary: str):
    # Legacy: PostgreSQL
    LLMTraceSummary.objects.create(
        team=team,
        trace_id=trace_id,
        analysis_theme_id=theme_id,
        summary=summary
    )

    # New: ClickHouse event
    capture_event(
        event="$ai_trace_summary",
        distinct_id="system",
        properties={
            "$trace_id": trace_id,
            "$analysis_theme_id": theme_id,
            "$summary": summary,
            ...
        }
    )

# Phase 2: Read from both, write to events only
# Phase 3: Read from events only, deprecate PostgreSQL table
```

### Phase 2: Add Theme Configs Table

```python
# ee/models/llm_traces_analysis_themes.py

class AnalysisThemeConfig(UUIDTModel):
    """Stored configuration for analysis themes"""

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    theme_id = models.CharField(max_length=100, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    # Config as JSON (serialized AnalysisTheme)
    config = models.JSONField()

    # Execution
    enabled = models.BooleanField(default=True)
    schedule = models.CharField(max_length=100, null=True)  # Cron expression
    last_run_at = models.DateTimeField(null=True)
    last_run_status = models.CharField(max_length=50, null=True)  # success, error, running

    # Built-in vs. custom
    is_builtin = models.BooleanField(default=False)

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "enabled"]),
            models.Index(fields=["team", "theme_id"]),
        ]
        unique_together = [("team", "theme_id")]
```

### Embeddings and the `rendering` Field

**What is `rendering`?**

`rendering` is a field in the ClickHouse `posthog_document_embeddings` table that acts as a **namespace** for scoping similarity searches. It's part of the existing PostHog document embeddings infrastructure.

**ClickHouse Schema:**

```sql
CREATE TABLE posthog_document_embeddings (
    team_id UInt64,
    product String,           -- "llm_traces_summaries"
    document_type String,     -- "llm_trace_summary"
    rendering String,         -- ← NAMESPACE (scopes similarity searches)
    document_id String,       -- trace_id
    content String,           -- The summary text
    vector Array(Float32),    -- 3072-dim embedding
    model String,             -- "text-embedding-3-large-3072"
    timestamp DateTime64
)
ENGINE = MergeTree()
ORDER BY (team_id, product, document_type, rendering, document_id)
```

**How It's Used:**

```python
# When searching for similar summaries
similarity_query = DocumentSimilarityQuery(
    renderings=["llm_traces_summary_error_analysis"],  # ← Filter by rendering
    # This ensures we only compare within this theme's embedding space
)

# ClickHouse query effectively becomes:
SELECT document_id, distance(vector, query_vector) as dist
FROM posthog_document_embeddings
WHERE team_id = ?
  AND product = 'llm_traces_summaries'
  AND rendering = 'llm_traces_summary_error_analysis'  -- ← Key filter
ORDER BY dist ASC
LIMIT 100
```

**For Themes: Separate Embedding Spaces**

Each theme gets its own `rendering` namespace:

```python
# Old (single space - all summaries mixed together):
rendering = "issues_search"

# New (per-theme - separate spaces):
rendering = f"llm_traces_summary_{theme_id}"

# Examples:
# - "llm_traces_summary_error_analysis"     → Error theme embeddings
# - "llm_traces_summary_ux_issues"          → UX theme embeddings
# - "llm_traces_summary_feature_requests"   → Feature theme embeddings
```

**Why Separate Spaces?**

```python
# Same trace, different summaries per theme:
trace_123 = "User checkout flow with payment timeout"

# Error theme prompt → Summary 1
error_summary = "Payment gateway timeout after 30s, Stripe 504 error"
error_embedding = embed(error_summary)
# Stored with rendering="llm_traces_summary_error_analysis"

# UX theme prompt → Summary 2
ux_summary = "User confused by timeout message, no retry button visible"
ux_embedding = embed(ux_summary)
# Stored with rendering="llm_traces_summary_ux_issues"

# Different embeddings, different similarity spaces!
# When searching errors, we only match against other error summaries
# When searching UX issues, we only match against other UX summaries
```

**Benefits:**

- ✅ Prevents cross-contamination between themes
- ✅ Error clusters contain only errors (not mixed with UX issues)
- ✅ Each theme has independent similarity space
- ✅ Can tune clustering parameters per theme
- ✅ Reuses existing PostHog infrastructure

### Phase 4: ClickHouse for Summaries (Optional)

```sql
CREATE TABLE posthog_llm_trace_summaries (
    team_id UInt64,
    trace_id String,
    summary_type String,
    summary String,
    created_at DateTime64(3, 'UTC'),

    -- For full-text search
    INDEX summary_text summary TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (team_id, trace_id, summary_type)
```

## API Endpoints (Phase 2)

```python
# ee/api/llm_traces_summarization.py

@router.get("/api/projects/{team_id}/llm_traces/summarization/configs")
def list_configs(team_id: int):
    """List all summarization configs for a team"""
    pass

@router.post("/api/projects/{team_id}/llm_traces/summarization/configs")
def create_config(team_id: int, config: TraceSummarizationConfig):
    """Create a new summarization config"""
    pass

@router.post("/api/projects/{team_id}/llm_traces/summarization/configs/{config_id}/run")
def run_config(team_id: int, config_id: str):
    """Manually trigger a summarization run"""
    pass

@router.get("/api/projects/{team_id}/llm_traces/summarization/results/{run_id}")
def get_results(team_id: int, run_id: str):
    """Get results of a summarization run"""
    pass
```

## User Interface Design (Phase 3)

### Theme Management Page

**Location**: Settings → LLM Analytics → Analysis Themes

```text
┌─────────────────────────────────────────────────────────────────┐
│ Analysis Themes                                      + New Theme │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│ Built-in Themes                                                   │
│ ┌───────────────────────────────────────────────────────────┐   │
│ │ [✓] Error Analysis                            Last: 2h ago │   │
│ │     Find and categorize errors, exceptions, and failures   │   │
│ │     500 traces analyzed • 12 clusters • View Results →     │   │
│ ├───────────────────────────────────────────────────────────┤   │
│ │ [✓] UX Issues                                 Last: 2h ago │   │
│ │     Identify friction points and frustrations              │   │
│ │     3,000 traces analyzed • 24 clusters • View Results →   │   │
│ ├───────────────────────────────────────────────────────────┤   │
│ │ [ ] Feature Requests                         Last: 3d ago  │   │
│ │     Extract feature requests and suggestions               │   │
│ │     Disabled • Configure →                                 │   │
│ └───────────────────────────────────────────────────────────┘   │
│                                                                   │
│ Custom Themes                                                     │
│ ┌───────────────────────────────────────────────────────────┐   │
│ │ [✓] Payment Errors                           Last: 30m ago │   │
│ │     Payment-specific error analysis                        │   │
│ │     127 traces analyzed • 5 clusters • View Results →      │   │
│ │     Edit • Duplicate • Delete                              │   │
│ └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Theme Configuration Form

**Create/Edit Theme**

```text
┌─────────────────────────────────────────────────────────────────┐
│ Create Analysis Theme                                        × │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│ Name *                                                            │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Payment Errors                                              │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ Description                                                       │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Analyze payment-related errors in checkout flow            │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ Base Filters (optional)                                          │
│ Apply to all themes in this project                              │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ + Add filter                                                │ │
│ │ ┌─────────────────────────────────────────────────────────┐ │ │
│ │ │ $ai_span_name     equals     checkout                   │ │ │
│ │ └─────────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ Theme-Specific Filters                                           │
│ Narrow down to traces relevant for this theme                    │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ + Add filter                                                │ │
│ │ ┌─────────────────────────────────────────────────────────┐ │ │
│ │ │ $ai_error     is set                                    │ │ │
│ │ └─────────────────────────────────────────────────────────┘ │ │
│ │ ┌─────────────────────────────────────────────────────────┐ │ │
│ │ │ $ai_output    contains     payment                      │ │ │
│ │ └─────────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ ⚡ Preview: ~127 traces match                                      │
│                                                                   │
│ Sampling (optional)                                               │
│ Analyze a subset of traces for cost efficiency                    │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Sample rate: [10%  ▼]                                       │ │
│ │                                                             │ │
│ │ ⚡ With 10% sampling:                                        │ │
│ │   • ~13 traces will be analyzed (vs 127)                   │ │
│ │   • Estimated cost: $0.13 (vs $1.27)                       │ │
│ │   • 90% cost savings!                                       │ │
│ │                                                             │ │
│ │ 💡 Tip: 10% sampling is often sufficient to find patterns  │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ Analysis Prompt                                                   │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ ▼ Use template: Error Analysis                             │ │
│ │                                                             │ │
│ │ Analyze this trace for payment errors.                     │ │
│ │ Identify:                                                   │ │
│ │ - Error type (timeout, decline, validation, etc.)          │ │
│ │ - Root cause                                                │ │
│ │ - Impact on checkout conversion                            │ │
│ │                                                             │ │
│ │ If no errors - return only "No errors found".              │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ Schedule                                                          │
│ ○ Manual   ● Daily at 2:00 AM   ○ Weekly   ○ Custom             │
│                                                                   │
│ Advanced                                                          │
│ ▼ Stringifier: Generic LLMA                                      │
│ ▼ LLM Model: Gemini 2.5 Flash Lite                               │
│ ▼ Clustering: Enabled (25-100 traces per cluster)                │
│                                                                   │
│                                  [Cancel] [Test Theme] [Create] │
└─────────────────────────────────────────────────────────────────┘
```

### Theme Results Dashboard

**View Results for a Theme**

```text
┌─────────────────────────────────────────────────────────────────┐
│ Payment Errors Theme                         Last run: 30m ago   │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│ Overview                                                          │
│ ┌─────────────┬─────────────┬─────────────┬─────────────┐      │
│ │ 127 traces  │ 5 clusters  │ 94% success │ $1.27 cost  │      │
│ └─────────────┴─────────────┴─────────────┴─────────────┘      │
│                                                                   │
│ Clusters                                    Sort: Size ▼         │
│ ┌───────────────────────────────────────────────────────────┐   │
│ │ Cluster 1: Stripe Timeout Errors (42 traces)             │   │
│ │ Payment gateway timeouts during checkout, typically      │   │
│ │ after 30s. Affects 3% of checkout attempts.              │   │
│ │ [View Traces] [Create Alert] [Export to Notebook]        │   │
│ ├───────────────────────────────────────────────────────────┤   │
│ │ Cluster 2: Card Declined Errors (35 traces)              │   │
│ │ Cards declined by issuer, mostly insufficient funds.     │   │
│ │ [View Traces] [Create Alert] [Export to Notebook]        │   │
│ └───────────────────────────────────────────────────────────┘   │
│                                                                   │
│ Trend (Last 7 days)                                               │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │     150│                                        ╭─╮           │ │
│ │     100│              ╭───╮       ╭──╮      ╭──╯ ╰╮          │ │
│ │      50│     ╭────╮╭──╯   ╰───╮╭──╯  ╰──╮╭──╯     ╰╮         │ │
│ │       0│─────╯    ╰╯          ╰╯        ╰╯         ╰─────   │ │
│ │        └──────────────────────────────────────────────────   │ │
│ │        Mon   Tue   Wed   Thu   Fri   Sat   Sun              │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ Cross-Theme Insights                                              │
│ 23 traces also appear in "UX Issues" theme →                     │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Testing Strategy

### Unit Tests

- Each stringifier with various trace formats
- Theme-based collection with filter combinations
- Cache hit/miss scenarios
- Prompt template rendering
- Config validation
- Stringifier factory

### Integration Tests

- End-to-end pipeline with multiple themes
- Theme-specific trace filtering
- Cache reuse across themes
- Multiple stringifiers on same trace
- Backward compatibility (PostHog AI traces)
- Theme-scoped embeddings and clustering

### Performance Tests

- Cache performance (hit rate, latency)
- Cost comparison: naive vs. theme-filtered
- Parallel theme execution (Phase 4)
- Large-scale clustering per theme

### Test Data

```python
# ee/hogai/llm_traces_summaries/tests/fixtures.py

# OpenAI trace example
OPENAI_TRACE = LLMTrace(
    id="openai-123",
    events=[
        LLMTraceEvent(
            event="$ai_generation",
            properties={
                "$ai_input": [{"role": "user", "content": "Hello"}],
                "$ai_output_choices": [{"message": {"role": "assistant", "content": "Hi!"}}],
                "$ai_model": "gpt-4"
            }
        )
    ]
)

# Anthropic trace example
ANTHROPIC_TRACE = ...

# LangChain trace example
LANGCHAIN_TRACE = ...

# PostHog AI trace example (existing)
POSTHOG_AI_TRACE = ...
```

## Performance Considerations

### Bottlenecks

1. **Stringification**: Iterate 100s-1000s of traces
2. **LLM calls**: Parallel async requests (rate limited)
3. **Embeddings**: Kafka throughput, ClickHouse writes
4. **Clustering**: CPU-intensive (KMeans on large datasets)

### Optimizations

1. **Batch processing**: 100 traces at a time
2. **Parallel LLM calls**: TaskGroup for async
3. **Caching**: Don't re-stringify/summarize existing traces
4. **Sampling**: For large datasets, sample before clustering
5. **Progressive results**: Stream results as they're available

## Migration Path

### Week 1-2: Port Formatters

- Port TS formatters to Python
- Unit tests for all trace formats
- Benchmark stringification performance

### Week 3: Stringifier Infrastructure

- Create base classes and factory
- Integrate with existing pipeline
- Feature flag for generic stringifier

### Week 4-5: Config System

- Define config schema
- Add config storage
- Update Temporal workflow

### Week 6-7: Testing & Refinement

- Integration tests
- User testing with real traces
- Performance optimization

### Week 8: Internal Rollout

- Deploy to staging
- Test with PostHog AI traces
- Gradual rollout to production

## Open Technical Questions

1. **Performance**: Can Python match TS formatter performance?
    - Benchmark needed
    - Consider Cython if too slow

2. **Format detection**: Auto-detect vs. explicit config?
    - Start with explicit, add auto-detect later
    - Cache detection results per trace

3. **Error handling**: What if stringifier fails mid-batch?
    - Skip trace and log warning
    - Don't fail entire pipeline

4. **Versioning**: How to handle formatter changes?
    - Version stringifiers (v1, v2, etc.)
    - Re-run summaries on new versions?

## Next Steps

1. Create proof-of-concept: Port one formatter to Python
2. Test with real OpenAI/Anthropic traces
3. Benchmark performance vs. existing stringifier
4. Finalize config schema with team
5. Create Phase 1 implementation tickets
