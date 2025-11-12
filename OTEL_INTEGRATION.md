# OpenTelemetry (OTLP) Integration for LLM Analytics

PostHog now supports ingesting LLM traces via the standard OpenTelemetry Protocol (OTLP), making it compatible with popular LLM observability frameworks like OpenLLMetry, LangChain, OpenLIT, and any OTLP-compliant instrumentation library.

## Overview

The OTLP endpoint accepts traces in the industry-standard OpenTelemetry format and automatically maps them to PostHog's LLM analytics events, enabling you to:

- Track LLM requests, responses, and embeddings
- Monitor token usage and costs
- Analyze latency and performance
- Debug errors and trace execution flows
- Correlate LLM activity with user behavior

## Endpoint Details

**URL**: `https://your-posthog-instance.com/api/public/otel/v1/traces`

**Method**: `POST`

**Content-Type**: `application/x-protobuf`

**Authentication**: Bearer token (use your PostHog project API key)

## Quick Start

### 1. Python with OpenLLMetry

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.openai import OpenAIInstrumentor

# Configure OTLP exporter to send to PostHog
otlp_exporter = OTLPSpanExporter(
    endpoint="https://your-posthog-instance.com/api/public/otel/v1/traces",
    headers={"Authorization": "Bearer your_project_api_key"}
)

# Set up tracer provider
resource = Resource.create({"service.name": "my-llm-app"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

# Instrument OpenAI (or other LLM libraries)
OpenAIInstrumentor().instrument()

# Now all OpenAI calls will be traced and sent to PostHog
import openai
client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### 2. LangChain with OTLP Export

```python
import os
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate

# Set environment variables for OTLP export
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://your-posthog-instance.com/api/public/otel"
os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = "Authorization=Bearer your_project_api_key"
os.environ["LANGSMITH_OTEL_ENABLED"] = "true"

# Use LangChain as normal - traces automatically sent to PostHog
llm = ChatOpenAI(model="gpt-4")
prompt = ChatPromptTemplate.from_template("Tell me a joke about {topic}")
chain = prompt | llm

result = chain.invoke({"topic": "OpenTelemetry"})
```

### 3. TypeScript/JavaScript with OpenLLMetry

```typescript
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { OpenAIInstrumentation } from '@traceloop/instrumentation-openai';

const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({
    url: 'https://your-posthog-instance.com/api/public/otel/v1/traces',
    headers: {
      'Authorization': 'Bearer your_project_api_key'
    }
  }),
  instrumentations: [
    new OpenAIInstrumentation()
  ]
});

sdk.start();

// Now use OpenAI SDK - all calls will be traced
import OpenAI from 'openai';
const openai = new OpenAI();

const completion = await openai.chat.completions.create({
  model: 'gpt-4',
  messages: [{ role: 'user', content: 'Hello!' }]
});
```

### 4. Generic OTLP SDK Configuration

For any OTLP-compatible SDK, configure these environment variables:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://your-posthog-instance.com/api/public/otel"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer your_project_api_key"
export OTEL_SERVICE_NAME="my-llm-application"
```

## Semantic Conventions

PostHog automatically maps OpenTelemetry GenAI semantic conventions to PostHog AI properties:

### Model Information

| OpenTelemetry Attribute | PostHog Property | Description |
|------------------------|------------------|-------------|
| `gen_ai.system` | `$ai_provider` | LLM provider (e.g., "openai", "anthropic") |
| `gen_ai.request.model` | `$ai_model` | Model name (e.g., "gpt-4", "claude-3-opus") |
| `gen_ai.provider.name` | `$ai_provider` | Alternative provider attribute |

### Token Usage

| OpenTelemetry Attribute | PostHog Property | Description |
|------------------------|------------------|-------------|
| `gen_ai.usage.prompt_tokens` | `$ai_prompt_tokens` | Input tokens consumed |
| `gen_ai.usage.completion_tokens` | `$ai_completion_tokens` | Output tokens generated |
| `gen_ai.usage.total_tokens` | `$ai_total_tokens` | Total tokens used |

### Request Parameters

| OpenTelemetry Attribute | PostHog Property | Description |
|------------------------|------------------|-------------|
| `gen_ai.request.temperature` | `$ai_temperature` | Sampling temperature |
| `gen_ai.request.max_tokens` | `$ai_max_tokens` | Maximum tokens to generate |
| `gen_ai.request.top_p` | `$ai_top_p` | Nucleus sampling parameter |
| `gen_ai.request.frequency_penalty` | `$ai_frequency_penalty` | Frequency penalty |
| `gen_ai.request.presence_penalty` | `$ai_presence_penalty` | Presence penalty |

### Tracing & Hierarchy

| OpenTelemetry Attribute | PostHog Property | Description |
|------------------------|------------------|-------------|
| `trace_id` | `$ai_trace_id` | Unique trace identifier |
| `span_id` | `$ai_span_id` | Unique span identifier |
| `parent_span_id` | `$ai_parent_id` | Parent span identifier |
| `span.name` | `$ai_span_name` | Human-readable span name |
| Duration (calculated) | `$ai_latency` | Request latency in milliseconds |

### Session & Agent Tracking

| OpenTelemetry Attribute | PostHog Property | Description |
|------------------------|------------------|-------------|
| `gen_ai.conversation.id` | `$ai_session_id` | Conversation/session identifier |
| `gen_ai.agent.id` | `$ai_agent_id` | Agent identifier |
| `gen_ai.agent.name` | `$ai_agent_name` | Agent name |

### Response Metadata

| OpenTelemetry Attribute | PostHog Property | Description |
|------------------------|------------------|-------------|
| `gen_ai.response.id` | `$ai_response_id` | Response ID from provider |
| `gen_ai.response.finish_reasons` | `$ai_finish_reason` | Why generation stopped |

### Error Handling

| OpenTelemetry Attribute | PostHog Property | Description |
|------------------------|------------------|-------------|
| `status.code=ERROR` | `$ai_is_error=true` | Indicates error occurred |
| `status.message` | `$ai_error` | Error message |
| `http.status_code` | `$ai_status_code` | HTTP status code |
| `error.type` | `$ai_error_type` | Error type/class |

## Event Types

PostHog automatically categorizes spans into appropriate event types:

- **`$ai_generation`**: LLM completion requests (chat, text generation)
- **`$ai_embedding`**: Embedding generation operations
- **`$ai_span`**: Generic AI operation spans (preprocessing, etc.)

## Advanced Configuration

### Custom Attributes

Any attributes not in the standard mapping are preserved with an `otel.` prefix:

```python
# In your instrumentation
from opentelemetry import trace

current_span = trace.get_current_span()
current_span.set_attribute("custom.user_id", "user_123")
current_span.set_attribute("custom.environment", "production")

# These become:
# - otel.custom.user_id: "user_123"
# - otel.custom.environment: "production"
```

### Resource Attributes

Resource-level attributes (e.g., `service.name`, `service.version`) are automatically included:

```python
from opentelemetry.sdk.resources import Resource

resource = Resource.create({
    "service.name": "recommendation-engine",
    "service.version": "2.1.0",
    "deployment.environment": "production"
})
```

### Sampling

Control which traces are sent to PostHog using OTLP SDK sampling:

```python
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

# Sample 10% of traces
provider = TracerProvider(
    sampler=TraceIdRatioBased(0.1)
)
```

## Troubleshooting

### Authentication Errors

**Error**: `401 Unauthorized`

**Solution**: Ensure you're using the correct project API key in the `Authorization` header:
```
Authorization: Bearer phc_xxxxx
```

### Content-Type Errors

**Error**: `415 Unsupported Media Type`

**Solution**: Ensure your OTLP exporter is configured for HTTP/protobuf, not gRPC:
```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
# NOT: from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
```

### Missing Traces

**Issue**: Traces not appearing in PostHog

**Solutions**:
1. Check that spans are being exported (enable debug logging)
2. Verify the endpoint URL is correct
3. Ensure Bearer token authentication is configured
4. Check that spans have the required trace_id and span_id

### Debug Logging

Enable debug logging to troubleshoot:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("opentelemetry").setLevel(logging.DEBUG)
```

## Compatibility

PostHog's OTLP endpoint is compatible with:

- ✅ OpenLLMetry
- ✅ LangChain / LangSmith OTLP export
- ✅ OpenLIT
- ✅ Traceloop
- ✅ Any OTLP-compliant SDK using HTTP/protobuf
- ❌ gRPC protocol (use HTTP/protobuf instead)

## Migration from Custom Integrations

If you're currently using PostHog's `/i/v0/ai` endpoint directly, you can now switch to standard OTLP instrumentation:

**Before (Custom Integration)**:
```python
# Manual event capture
posthog.capture(
    distinct_id="user_123",
    event="$ai_generation",
    properties={
        "$ai_model": "gpt-4",
        "$ai_provider": "openai",
        # ... many manual properties
    }
)
```

**After (OTLP)**:
```python
# Automatic tracing with OpenLLMetry
from openinference.instrumentation.openai import OpenAIInstrumentor
OpenAIInstrumentor().instrument()

# That's it! All LLM calls now automatically tracked
```

## Example: Complete Application

```python
#!/usr/bin/env python3
"""
Complete example: LLM application with PostHog OTLP tracing
"""

import os
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from openinference.instrumentation.openai import OpenAIInstrumentor
import openai

# Configure PostHog OTLP endpoint
POSTHOG_HOST = os.getenv("POSTHOG_HOST", "https://app.posthog.com")
POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY")

otlp_exporter = OTLPSpanExporter(
    endpoint=f"{POSTHOG_HOST}/api/public/otel/v1/traces",
    headers={"Authorization": f"Bearer {POSTHOG_API_KEY}"}
)

# Set up OpenTelemetry
resource = Resource.create({
    "service.name": "chatbot-service",
    "service.version": "1.0.0",
    "deployment.environment": "production"
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

# Instrument OpenAI
OpenAIInstrumentor().instrument()

# Use OpenAI - all calls automatically traced
def chat(user_message: str, user_id: str) -> str:
    """Send a chat message and get response."""

    # Add custom attributes to the trace
    current_span = trace.get_current_span()
    current_span.set_attribute("user.id", user_id)
    current_span.set_attribute("chat.session_id", f"session_{user_id}")

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_message}
        ],
        temperature=0.7,
        max_tokens=500
    )

    return response.choices[0].message.content

if __name__ == "__main__":
    # Example usage
    response = chat("What is OpenTelemetry?", user_id="user_123")
    print(f"Response: {response}")

    # Traces are automatically sent to PostHog!
```

## Next Steps

1. **Instrument your LLM application** using one of the examples above
2. **View traces in PostHog** under LLM Analytics
3. **Create dashboards** to monitor token usage, latency, and errors
4. **Set up alerts** for high error rates or latency spikes
5. **Correlate LLM usage** with user behavior and product metrics

## Support

For questions or issues:
- GitHub: https://github.com/PostHog/posthog/issues
- Community: https://posthog.com/community
- Docs: https://posthog.com/docs/llm-analytics
