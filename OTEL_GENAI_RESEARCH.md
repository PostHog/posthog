# OpenTelemetry Gen AI Integration for PostHog LLM Analytics

**Research & Proposed Implementation Plan**

Date: November 13, 2025
Author: Research conducted via Claude Code

> 📊 **Architecture Details**: For detailed technical architecture with Mermaid diagrams, see [OTEL_GENAI_ARCHITECTURE.md](./OTEL_GENAI_ARCHITECTURE.md)

---

## Executive Summary

This document outlines a comprehensive approach for enabling PostHog LLM Analytics to accept OpenTelemetry (OTEL) traces with Gen AI semantic conventions. This would allow PostHog to ingest LLM telemetry from any framework or SDK that supports OTEL (OpenAI, Anthropic, LangChain, LlamaIndex, etc.) without requiring custom instrumentation.

**Key Recommendation**: Extend PostHog's existing OTEL Logs infrastructure to also support OTEL Traces, then layer Gen AI semantic convention mapping on top. This leverages existing infrastructure while enabling broad ecosystem compatibility.

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [OpenTelemetry Gen AI Conventions](#opentelemetry-gen-ai-conventions)
3. [Industry Approaches](#industry-approaches)
4. [Proposed Architecture](#proposed-architecture)
5. [Implementation Phases](#implementation-phases)
6. [Benefits & Considerations](#benefits--considerations)
7. [Technical Details](#technical-details)

---

## Current State Analysis

### PostHog's Existing OTEL Infrastructure

PostHog already has a **production-ready OTEL Logs ingestion system**:

**Service**: `rust/capture-logs/`

- **Protocol**: OTLP via gRPC (port 4317) and HTTP (port 4318)
- **Authentication**: JWT token with team_id claim
- **Processing**: Rust-based service that accepts OTEL log records
- **Storage**: Writes to Kafka for ClickHouse ingestion
- **Trace Support**: Already captures `trace_id` and `span_id` from log records

**Key Implementation Details** (`rust/capture-logs/src/log_record.rs`):

```rust
pub struct KafkaLogRow {
    pub uuid: String,
    pub trace_id: String,        // ✓ Already captured
    pub span_id: String,          // ✓ Already captured
    pub trace_flags: u32,
    pub timestamp: DateTime<Utc>,
    pub body: String,
    pub severity_text: String,
    pub service_name: String,
    pub resource_attributes: HashMap<String, String>,
    pub instrumentation_scope: String,
    pub event_name: String,       // ✓ Could map to gen_ai.operation.name
    pub attributes: HashMap<String, String>,  // ✓ Where Gen AI attributes go
    // ... more fields
}
```

**Current OTEL Configuration** (`otel-collector-config.dev.yaml`):

- Accepts OTLP logs via gRPC/HTTP
- Currently forwards logs to `capture-logs:4318`
- Supports traces but only exports to Jaeger (not PostHog)

### PostHog's LLM Analytics Event Model

PostHog LLM Analytics currently uses **custom PostHog events** (not OTEL):

**Event Types**:

- `$ai_generation` - Individual LLM API calls
- `$ai_span` - Logical spans with state transitions
- `$ai_embedding` - Embedding generation
- `$ai_trace` - Full trace with hierarchy

**Key Properties** (from `products/llm_analytics/backend/dashboard_templates.py`):

```javascript
properties: {
  $ai_trace_id: "...",           // Trace identifier
  $ai_span_id: "...",            // Span identifier (implied)
  $ai_model: "gpt-4",            // Model name
  $ai_total_cost_usd: 0.0042,    // Cost calculation
  $ai_latency: 1234,             // Response time in ms
  $ai_input: [...],              // Input messages
  $ai_output_choices: [...],     // Output completions
  $ai_is_error: false,           // Error flag
  $ai_http_status: 200,          // HTTP status
  // ... more properties
}
```

**Current Ingestion Flow**:

1. SDKs/frameworks send custom events to PostHog Events API
2. Events processed as standard PostHog events
3. Frontend queries these events using HogQL/Insights

---

## OpenTelemetry Gen AI Conventions

### Overview

The **OpenTelemetry Semantic Conventions for Gen AI** define standardized attributes for instrumenting generative AI operations. They are still in **Development** status but have broad industry adoption.

**Reference**: https://opentelemetry.io/docs/specs/semconv/gen-ai/

### Signal Types

Gen AI observability uses **all three OTEL signals**:

1. **Traces** (Primary): Model interactions and agent orchestration
   - **Model spans**: Direct AI model API calls
   - **Agent spans**: Higher-level orchestration (chains, workflows)

2. **Events**: Detailed input/output capture
   - Attached to spans as span events
   - Capture prompts, completions, tool calls

3. **Metrics**: Aggregated statistics
   - Request counts, latency, token usage, costs

### Key Attributes

Gen AI conventions define attributes in the `gen_ai.*` namespace:

**Request Attributes**:

```yaml
gen_ai.operation.name: "chat" | "completion" | "embedding"
gen_ai.system: "openai" | "anthropic" | "azure_ai_inference"
gen_ai.request.model: "gpt-4o"
gen_ai.request.temperature: 0.7
gen_ai.request.max_tokens: 1000
gen_ai.request.top_p: 1.0
```

**Response Attributes**:

```yaml
gen_ai.response.id: "chatcmpl-..."
gen_ai.response.model: "gpt-4o-2024-11-13"
gen_ai.response.finish_reasons: ["stop"]
```

**Usage Attributes**:

```yaml
gen_ai.usage.input_tokens: 150
gen_ai.usage.output_tokens: 42
gen_ai.usage.total_tokens: 192
```

**Message Content** (Events or Structured Attributes):

```yaml
# Flattened format:
gen_ai.prompt.0.role: "user"
gen_ai.prompt.0.content: "Hello, world"
gen_ai.completion.0.role: "assistant"
gen_ai.completion.0.content: "Hi there!"

# OR JSON format:
gen_ai.prompt_json: '[{"role":"user","content":"..."}]'
gen_ai.completion_json: '[{"role":"assistant","content":"..."}]'
```

**Trace Context**:

- Standard OTEL `trace_id` and `span_id`
- Parent/child span relationships
- Trace hierarchy maintained through context propagation

---

## Industry Approaches

### 1. Braintrust

**URL**: https://www.braintrust.dev/docs/integrations/sdk-integrations/opentelemetry

**Ingestion**:

- OTLP endpoint: `https://api.braintrust.dev/otel`
- Accepts traces via gRPC and HTTP
- Supports standard OTEL exporters

**Processing**:

- Maps Gen AI semantic conventions to Braintrust data model
- Converts `gen_ai.prompt` → structured inputs
- Converts `gen_ai.completion` → structured outputs
- Extracts `gen_ai.usage.*` → token metrics
- Automatically categorizes spans as "llm", "tool", "task" based on `gen_ai.operation.name`
- Supports both flattened and JSON-serialized message formats

**Span Processor**:

- Provides custom `BraintrustSpanProcessor` for Python/TypeScript
- Allows rich instrumentation beyond basic OTEL

### 2. Langfuse

**URL**: https://langfuse.com/guides/cookbook/otel_integration_python_sdk

**Architecture**:

- Acts as "OpenTelemetry Backend"
- Endpoint: `/api/public/otlp`
- HTTP with Basic Auth (API key as credentials)

**Mapping Strategy**:

- Transforms OTEL spans → Langfuse traces/observations
- Follows OpenTelemetry Gen AI Conventions
- Handles both formats:
  - Flattened: `gen_ai.prompt.0.role`, `gen_ai.request.model`
  - JSON: `gen_ai.prompt_json`, `gen_ai.completion_json`
- Custom attributes for Langfuse-specific features:
  - `langfuse.session.id`
  - `langfuse.user.id`
  - `langfuse.tags`
  - `langfuse.prompt.name`

**Philosophy**:

- No proprietary SDK required
- Works with any OTEL-compatible instrumentation
- Framework-agnostic (LangChain, LlamaIndex, custom)

### 3. LangSmith (LangChain)

**URL**: https://docs.langchain.com/langsmith/trace-with-opentelemetry

**Approach**:

- OTEL-compatible but LangChain-centric
- Focused on tracing LangChain applications
- Uses OTEL for distributed tracing across services

---

## Proposed Architecture

### High-Level Overview

The architecture extends PostHog's existing OTEL Logs infrastructure to support OTEL Traces with Gen AI semantic conventions. The system consists of:

1. **Ingestion Layer**: New `capture-traces` service (mirrors `capture-logs`)
2. **Transformation Layer**: Gen AI semantic convention mapper
3. **Storage Layer**: Kafka → ClickHouse (existing pipeline)
4. **Query Layer**: PostHog LLM Analytics UI (existing)

**Key Design Principles**:

- Reuse existing patterns from `capture-logs`
- Support both direct export and collector-based ingestion
- Maintain backward compatibility with existing custom events
- Enable universal framework support via OTEL standards

> 📊 **For detailed architecture diagrams and component specifications, see [OTEL_GENAI_ARCHITECTURE.md](./OTEL_GENAI_ARCHITECTURE.md)**

### Core Components

#### 1. Trace Ingestion Service (NEW)

**Location**: `rust/capture-traces/`

**Purpose**: Accept OTLP traces (complementing existing logs service)

**Responsibilities**:

- Accept OTLP Trace exports via gRPC (port 4317) and HTTP (port 4318)
- JWT authentication (team_id claim)
- Extract Gen AI semantic convention attributes
- Convert to PostHog event format
- Write to Kafka for ClickHouse ingestion

**Implementation**: Rust service (similar to `capture-logs`)

#### 2. Gen AI Semantic Convention Mapper (NEW)

**Location**: `rust/capture-traces/src/genai_mapper.rs`

**Purpose**: Transform OTEL Gen AI spans → PostHog LLM Analytics events

**Mapping Logic**:

```rust
// Pseudo-code for mapping
fn map_otel_span_to_posthog_event(span: Span) -> PostHogEvent {
    let operation = span.attributes.get("gen_ai.operation.name");

    match operation {
        "chat" | "completion" => Event {
            event: "$ai_generation",
            properties: {
                "$ai_trace_id": span.trace_id,
                "$ai_span_id": span.span_id,
                "$ai_parent_span_id": span.parent_span_id,
                "$ai_model": span.attributes["gen_ai.request.model"],
                "$ai_input": extract_prompt(span),
                "$ai_output_choices": extract_completion(span),
                "$ai_input_tokens": span.attributes["gen_ai.usage.input_tokens"],
                "$ai_output_tokens": span.attributes["gen_ai.usage.output_tokens"],
                "$ai_total_cost_usd": calculate_cost(span),
                "$ai_latency": span.duration_ms,
                "$ai_provider": span.attributes["gen_ai.system"],
                // Map other attributes...
            }
        },
        "embedding" => Event {
            event: "$ai_embedding",
            properties: {
                // Similar mapping for embeddings...
            }
        },
        _ => Event {
            event: "$ai_span",
            properties: {
                // Generic span mapping...
            }
        }
    }
}

fn extract_prompt(span: Span) -> Vec<Message> {
    // Try JSON format first
    if let Some(json) = span.attributes.get("gen_ai.prompt_json") {
        return parse_json_messages(json);
    }

    // Fall back to flattened format
    let mut messages = vec![];
    let mut i = 0;
    while let Some(role) = span.attributes.get(&format!("gen_ai.prompt.{}.role", i)) {
        let content = span.attributes.get(&format!("gen_ai.prompt.{}.content", i));
        messages.push(Message { role, content });
        i += 1;
    }
    messages
}

fn calculate_cost(span: Span) -> f64 {
    // Implement cost calculation based on model and token usage
    // Similar to existing LLM Analytics cost calculation
    let model = span.attributes.get("gen_ai.response.model").or(
        span.attributes.get("gen_ai.request.model")
    );
    let input_tokens = span.attributes.get("gen_ai.usage.input_tokens");
    let output_tokens = span.attributes.get("gen_ai.usage.output_tokens");

    // Use PostHog's pricing model
    pricing::calculate_llm_cost(model, input_tokens, output_tokens)
}
```

#### 3. Enhanced OTEL Collector Config

**Location**: `otel-collector-config.dev.yaml`

**Changes**:

```yaml
exporters:
  otlphttp/logs:
    endpoint: 'http://capture-logs:4318'  # Existing
    # ... existing config

  otlphttp/traces:  # NEW
    endpoint: 'http://capture-traces:4318'
    compression: none
    tls:
      insecure: true
    headers:
      authorization: Bearer ${POSTHOG_TOKEN}

service:
  pipelines:
    traces:  # Modified
      receivers: [otlp]
      processors: [batch]
      exporters: [otlphttp/traces]  # Send to PostHog instead of Jaeger

    logs:  # Existing
      receivers: [otlp, filelog]
      processors: [batch]
      exporters: [otlphttp/logs]
```

#### 4. ClickHouse Schema Extensions

**Location**: `posthog/clickhouse/migrations/`

**Considerations**:

- Existing events table likely already supports the required properties
- May need to add indexes for efficient trace queries
- Consider materialized views for common aggregations

**Potential Migration**:

```sql
-- Add index for efficient trace queries if needed
ALTER TABLE events
ADD INDEX idx_ai_trace_id (properties.$ai_trace_id) TYPE bloom_filter;

-- Materialized view for common LLM metrics (optional)
CREATE MATERIALIZED VIEW llm_metrics_mv
ENGINE = AggregatingMergeTree()
ORDER BY (team_id, timestamp, model)
AS SELECT
    team_id,
    toStartOfHour(timestamp) as timestamp,
    properties.$ai_model as model,
    count() as request_count,
    sum(properties.$ai_input_tokens) as total_input_tokens,
    sum(properties.$ai_output_tokens) as total_output_tokens,
    sum(properties.$ai_total_cost_usd) as total_cost,
    avg(properties.$ai_latency) as avg_latency
FROM events
WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding')
GROUP BY team_id, timestamp, model;
```

---

## Implementation Phases

### Phase 1: Foundation (2-3 weeks)

**Goal**: Basic OTLP trace ingestion

**Tasks**:

1. Create `rust/capture-traces/` service
   - Clone `capture-logs/` as template
   - Modify to accept OTLP traces instead of logs
   - JWT authentication with team_id
   - Basic span → event conversion (no Gen AI mapping yet)

2. Update OTEL Collector configuration
   - Add trace export to capture-traces
   - Test with sample OTLP traces

3. Test infrastructure
   - Unit tests for span parsing
   - Integration tests with OTEL SDK
   - Load testing

**Deliverables**:

- Working `capture-traces` service
- OTLP traces flowing to PostHog events
- Basic documentation

**Validation**:

- Send OTLP trace → appears as PostHog event
- Trace ID and span ID preserved
- Authentication working

### Phase 2: Gen AI Mapping (2-3 weeks)

**Goal**: Transform OTEL Gen AI spans → PostHog LLM Analytics events

**Tasks**:

1. Implement Gen AI semantic convention mapper
   - Parse Gen AI attributes (`gen_ai.*`)
   - Map to PostHog LLM properties (`$ai_*`)
   - Support both flattened and JSON message formats
   - Handle tool calls, function calling

2. Cost calculation integration
   - Reuse existing LLM pricing models
   - Support major providers (OpenAI, Anthropic, etc.)
   - Handle custom/unknown models

3. Hierarchy reconstruction
   - Build trace hierarchy from parent/child spans
   - Generate `$ai_trace` events with full structure
   - Maintain span relationships

4. Testing with real frameworks
   - OpenAI Python SDK with OTEL instrumentation
   - LangChain with OTEL
   - LlamaIndex with OTEL

**Deliverables**:

- Complete Gen AI attribute mapping
- Cost calculation working
- Trace hierarchy support
- Framework integration examples

**Validation**:

- OpenAI SDK trace → correct `$ai_generation` event
- LangChain chain → proper `$ai_trace` with hierarchy
- Costs calculated accurately
- All Gen AI attributes mapped

### Phase 3: Enhanced Features (2-3 weeks)

**Goal**: Production-ready with optimization and monitoring

**Tasks**:

1. Performance optimization
   - Batch processing of spans
   - Efficient attribute extraction
   - Connection pooling to Kafka

2. Error handling and observability
   - Comprehensive error logging
   - Prometheus metrics
   - Health checks
   - Rate limiting

3. Advanced mapping features
   - Custom attribute mapping (allow teams to map custom attributes)
   - Provider-specific optimizations
   - Sampling configuration
   - Filtering rules

4. Documentation and examples
   - Setup guides for major frameworks
   - Code examples (Python, JavaScript, Go)
   - Troubleshooting guide
   - Migration guide from custom events

**Deliverables**:

- Production-ready service
- Comprehensive monitoring
- Documentation site
- Example repositories

**Validation**:

- Performance benchmarks meet targets
- Monitoring dashboards operational
- Documentation complete
- Example apps working

### Phase 4: Ecosystem Integration (Ongoing)

**Goal**: Broad ecosystem support and community adoption

**Tasks**:

1. Pre-built integrations
   - OpenAI SDK wrapper
   - LangChain callback handler (complementing OTEL)
   - LlamaIndex instrumentation
   - Anthropic SDK support

2. Instrumentation libraries
   - PostHog OTEL distribution (pre-configured exporter)
   - Framework-specific helpers
   - Auto-instrumentation where possible

3. Community engagement
   - Blog posts and tutorials
   - Example projects
   - Community showcase
   - Support in forums/Discord

**Deliverables**:

- Integration packages for major frameworks
- Tutorial content
- Community examples

---

## Benefits & Considerations

### Benefits

#### 1. **Universal Compatibility**

- Works with **any framework** that supports OTEL
- No need to maintain framework-specific SDKs
- Future-proof as new frameworks adopt OTEL

#### 2. **Standards-Based**

- Follows OpenTelemetry semantic conventions
- Benefits from OTEL ecosystem growth
- Interoperable with other observability tools

#### 3. **Reduced Maintenance**

- Leverage community OTEL instrumentation
- Less custom instrumentation to maintain
- Automatic support for new providers

#### 4. **Rich Ecosystem**

- OTEL has auto-instrumentation for many frameworks
- Extensive tooling and documentation
- Large community support

#### 5. **Distributed Tracing**

- Natural support for multi-service architectures
- Trace LLM calls across microservices
- Better debugging of complex workflows

#### 6. **Backward Compatible**

- Existing custom event ingestion still works
- Teams can migrate at their own pace
- Dual ingestion during transition

### Considerations

#### 1. **Complexity**

- OTEL has a learning curve
- More moving parts (collector, exporters, etc.)
- Debugging can be harder initially

**Mitigation**:

- Provide pre-configured OTEL distributions
- Clear documentation and examples
- Support direct export (no collector required)

#### 2. **Cost Calculation**

- OTEL doesn't include cost information
- Must calculate from token usage + model pricing
- Pricing data needs maintenance

**Mitigation**:

- Reuse existing PostHog pricing models
- Provide cost calculation as a service
- Allow custom pricing tables

#### 3. **Attribute Completeness**

- Not all SDKs send complete Gen AI attributes
- Some frameworks have custom attributes
- JSON vs flattened format variations

**Mitigation**:

- Support both flattened and JSON formats
- Graceful handling of missing attributes
- Provider-specific attribute mapping

#### 4. **Performance**

- OTLP binary format has overhead
- Trace processing can be CPU-intensive
- High-volume scenarios need optimization

**Mitigation**:

- Rust implementation for performance
- Batch processing
- Efficient serialization/deserialization
- Horizontal scaling

#### 5. **Migration Path**

- Existing users have custom instrumentation
- May need to maintain dual systems temporarily
- Documentation for migration needed

**Mitigation**:

- Backward compatibility with existing events
- Migration guide with code examples
- Gradual rollout options

---

## Technical Details

### Authentication Flow

Authentication uses JWT tokens with team_id claims:

1. Application obtains PostHog API key
2. Exchange API key for JWT token containing team_id
3. OTEL exporter includes JWT in Authorization header
4. `capture-traces` validates JWT and extracts team_id
5. Events are tagged with team_id for data isolation

> 📊 **For detailed authentication sequence diagrams, see [OTEL_GENAI_ARCHITECTURE.md](./OTEL_GENAI_ARCHITECTURE.md#authentication--security)**

### Attribute Mapping Table

| OTEL Gen AI Attribute | PostHog Property | Notes |
|----------------------|------------------|-------|
| `trace_id` | `$ai_trace_id` | Binary → base64 |
| `span_id` | `$ai_span_id` | Binary → base64 |
| `parent_span_id` | `$ai_parent_span_id` | Binary → base64 |
| `gen_ai.operation.name` | Determines event type | chat→$ai_generation |
| `gen_ai.system` | `$ai_provider` | openai, anthropic, etc. |
| `gen_ai.request.model` | `$ai_model` | gpt-4, claude-3-opus |
| `gen_ai.response.model` | `$ai_model` | Prefer response over request |
| `gen_ai.prompt_json` | `$ai_input` | Parse JSON → array |
| `gen_ai.prompt.N.role` | `$ai_input[N].role` | Flattened format |
| `gen_ai.prompt.N.content` | `$ai_input[N].content` | Flattened format |
| `gen_ai.completion_json` | `$ai_output_choices` | Parse JSON → array |
| `gen_ai.completion.N.role` | `$ai_output_choices[N].role` | Flattened format |
| `gen_ai.completion.N.content` | `$ai_output_choices[N].content` | Flattened format |
| `gen_ai.usage.input_tokens` | `$ai_input_tokens` | Direct copy |
| `gen_ai.usage.output_tokens` | `$ai_output_tokens` | Direct copy |
| `gen_ai.usage.total_tokens` | `$ai_total_tokens` | Direct copy |
| `gen_ai.response.finish_reasons` | `$ai_finish_reason` | Array → first element |
| `gen_ai.request.temperature` | `$ai_temperature` | Direct copy |
| `gen_ai.request.max_tokens` | `$ai_max_tokens` | Direct copy |
| `gen_ai.request.top_p` | `$ai_top_p` | Direct copy |
| `span.status.code` | `$ai_is_error` | ERROR → true |
| `span.status.message` | `$ai_error_message` | Error details |
| `duration_ms` | `$ai_latency` | Span end - start |
| `http.status_code` | `$ai_http_status` | HTTP response code |
| Calculated | `$ai_total_cost_usd` | Calculate from tokens + model |

### Sample OTLP Trace → PostHog Event

**Input (OTLP Trace)**:

```json
{
  "resourceSpans": [{
    "resource": {
      "attributes": [
        {"key": "service.name", "value": {"stringValue": "my-llm-app"}}
      ]
    },
    "scopeSpans": [{
      "spans": [{
        "traceId": "5B8EFFF798038103D269B633813FC60C",
        "spanId": "EEE19B7EC3C1B173",
        "parentSpanId": "",
        "name": "chat",
        "kind": "SPAN_KIND_CLIENT",
        "startTimeUnixNano": "1544712660000000000",
        "endTimeUnixNano": "1544712661234000000",
        "attributes": [
          {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
          {"key": "gen_ai.system", "value": {"stringValue": "openai"}},
          {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
          {"key": "gen_ai.response.model", "value": {"stringValue": "gpt-4o-2024-11-13"}},
          {"key": "gen_ai.usage.input_tokens", "value": {"intValue": 150}},
          {"key": "gen_ai.usage.output_tokens", "value": {"intValue": 42}},
          {"key": "gen_ai.prompt_json", "value": {
            "stringValue": "[{\"role\":\"user\",\"content\":\"What is AI?\"}]"
          }},
          {"key": "gen_ai.completion_json", "value": {
            "stringValue": "[{\"role\":\"assistant\",\"content\":\"AI stands for...\"}]"
          }}
        ],
        "status": {"code": "STATUS_CODE_OK"}
      }]
    }]
  }]
}
```

**Output (PostHog Event)**:

```json
{
  "event": "$ai_generation",
  "distinct_id": "user_123",
  "properties": {
    "$ai_trace_id": "W47/95gDgQPSabYzgT/GDA==",
    "$ai_span_id": "7uGbfsw8sXM=",
    "$ai_parent_span_id": null,
    "$ai_provider": "openai",
    "$ai_model": "gpt-4o-2024-11-13",
    "$ai_input": [
      {"role": "user", "content": "What is AI?"}
    ],
    "$ai_output_choices": [
      {"role": "assistant", "content": "AI stands for..."}
    ],
    "$ai_input_tokens": 150,
    "$ai_output_tokens": 42,
    "$ai_total_tokens": 192,
    "$ai_total_cost_usd": 0.000825,
    "$ai_latency": 1234,
    "$ai_is_error": false,
    "$ai_service_name": "my-llm-app",
    "timestamp": "2018-12-13T14:11:00.000Z"
  }
}
```

### Cost Calculation Algorithm

```rust
fn calculate_cost(span: &Span) -> Option<f64> {
    let model = span.attributes.get("gen_ai.response.model")
        .or_else(|| span.attributes.get("gen_ai.request.model"))?;

    let input_tokens = span.attributes.get("gen_ai.usage.input_tokens")?.as_int()?;
    let output_tokens = span.attributes.get("gen_ai.usage.output_tokens")?.as_int()?;

    // Use PostHog's existing pricing model
    let pricing = PRICING_DB.get(model)?;

    let input_cost = (input_tokens as f64 / 1_000_000.0) * pricing.input_price_per_1m;
    let output_cost = (output_tokens as f64 / 1_000_000.0) * pricing.output_price_per_1m;

    Some(input_cost + output_cost)
}

// Example pricing database (matches existing LLM Analytics)
const PRICING_DB: HashMap<&str, Pricing> = hashmap! {
    "gpt-4o" => Pricing {
        input_price_per_1m: 2.50,
        output_price_per_1m: 10.00,
    },
    "gpt-4o-mini" => Pricing {
        input_price_per_1m: 0.15,
        output_price_per_1m: 0.60,
    },
    "claude-3-5-sonnet-20241022" => Pricing {
        input_price_per_1m: 3.00,
        output_price_per_1m: 15.00,
    },
    // ... more models
};
```

### Example: OpenAI with OTEL

**Python**:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
import openai

# Configure OTEL to send to PostHog
provider = TracerProvider()
exporter = OTLPSpanExporter(
    endpoint="https://app.posthog.com/otlp",  # Or your self-hosted endpoint
    headers={
        "Authorization": f"Bearer {POSTHOG_JWT_TOKEN}"
    }
)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

# Auto-instrument OpenAI
OpenAIInstrumentor().instrument()

# Use OpenAI normally - traces automatically sent to PostHog
client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is AI?"}]
)
```

**Result**: OTEL instrumentation automatically creates traces with Gen AI attributes, sent to PostHog, converted to `$ai_generation` events, visible in LLM Analytics dashboard.

---

## Conclusion

Implementing OpenTelemetry Gen AI support in PostHog LLM Analytics provides:

✅ **Universal compatibility** with any OTEL-enabled framework
✅ **Standards-based** approach following industry conventions
✅ **Reduced maintenance** by leveraging community instrumentation
✅ **Backward compatibility** with existing custom events
✅ **Future-proof** architecture as OTEL adoption grows

The proposed architecture builds on PostHog's existing OTEL Logs infrastructure, extending it to support traces with Gen AI semantic conventions. This enables PostHog to become the observability destination of choice for LLM applications, regardless of the underlying framework or SDK.

**Recommended Next Steps**:

1. ✅ Review and approve this proposal
2. Create technical design doc for Phase 1
3. Set up project tracking and milestones
4. Assign engineering resources
5. Begin Phase 1 implementation

---

## Appendix: References

### OpenTelemetry Resources

- Gen AI Semantic Conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
- OTEL Blog on Gen AI: https://opentelemetry.io/blog/2024/otel-generative-ai/
- Python Contrib (Gen AI): https://github.com/open-telemetry/opentelemetry-python-contrib

### Competitive Analysis

- Braintrust OTEL Integration: https://www.braintrust.dev/docs/integrations/sdk-integrations/opentelemetry
- Langfuse OTEL Integration: https://langfuse.com/guides/cookbook/otel_integration_python_sdk
- LangSmith OTEL Integration: https://docs.langchain.com/langsmith/trace-with-opentelemetry

### PostHog Resources

- Logs Product: https://posthog.com/docs/logs
- LLM Analytics: (internal docs)
- Existing capture-logs: `rust/capture-logs/`
- OTEL Instrumentation: `posthog/otel_instrumentation.py`

---

**Document Version**: 1.0
**Last Updated**: November 13, 2025
**Status**: Draft for Review
