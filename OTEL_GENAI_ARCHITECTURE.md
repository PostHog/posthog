# OpenTelemetry Gen AI Integration - Technical Architecture

**Detailed architectural design for OTEL-based Gen AI ingestion in PostHog**

Date: November 13, 2025

This document provides medium-level architectural details and diagrams for the OpenTelemetry Gen AI integration. For high-level overview and implementation plan, see [OTEL_GENAI_RESEARCH.md](./OTEL_GENAI_RESEARCH.md).

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Data Flow](#data-flow)
3. [Component Details](#component-details)
4. [Authentication & Security](#authentication--security)
5. [Message Transformation Pipeline](#message-transformation-pipeline)
6. [Deployment Architecture](#deployment-architecture)
7. [Integration Patterns](#integration-patterns)

---

## System Architecture

### High-Level System Diagram

```mermaid
graph TB
    subgraph "Client Applications"
        App1[LangChain App]
        App2[OpenAI App]
        App3[LlamaIndex App]
        App4[Custom App]
    end

    subgraph "OTEL Instrumentation"
        Inst1[OTEL SDK]
        Inst2[Auto-instrumentation]
    end

    subgraph "OTEL Collector (Optional)"
        Collector[OTEL Collector]
        CollectorRecv[OTLP Receiver]
        CollectorProc[Batch Processor]
        CollectorExp[OTLP Exporter]
    end

    subgraph "PostHog Ingestion"
        CaptureTraces[capture-traces Service]
        CaptureLogs[capture-logs Service]
        GenAIMapper[Gen AI Mapper]
        Auth[JWT Validator]
    end

    subgraph "Message Queue"
        Kafka[Kafka Topics]
        KafkaEvents[events_plugin_ingestion]
        KafkaLogs[logs]
    end

    subgraph "Storage & Query"
        ClickHouse[(ClickHouse)]
        EventsTable[events Table]
        LogsTable[logs Table]
    end

    subgraph "PostHog Frontend"
        Frontend[LLM Analytics UI]
        Dashboard[Dashboards]
        Traces[Traces View]
    end

    App1 --> Inst1
    App2 --> Inst1
    App3 --> Inst2
    App4 --> Inst1

    Inst1 --> Collector
    Inst2 --> Collector
    Inst1 -.Direct Export.-> CaptureTraces
    Inst2 -.Direct Export.-> CaptureTraces

    Collector --> CollectorRecv
    CollectorRecv --> CollectorProc
    CollectorProc --> CollectorExp
    CollectorExp --> CaptureTraces
    CollectorExp --> CaptureLogs

    CaptureTraces --> Auth
    Auth --> GenAIMapper
    GenAIMapper --> Kafka

    CaptureLogs --> Auth
    Auth --> Kafka

    Kafka --> KafkaEvents
    Kafka --> KafkaLogs

    KafkaEvents --> ClickHouse
    KafkaLogs --> ClickHouse

    ClickHouse --> EventsTable
    ClickHouse --> LogsTable

    EventsTable --> Frontend
    LogsTable --> Frontend

    Frontend --> Dashboard
    Frontend --> Traces

    style CaptureTraces fill:#e1f5ff
    style GenAIMapper fill:#e1f5ff
    style CaptureLogs fill:#d4edda
    style Collector fill:#fff3cd
```

### Component Interaction Sequence

```mermaid
sequenceDiagram
    participant App as LLM Application
    participant SDK as OTEL SDK
    participant Coll as OTEL Collector
    participant CT as capture-traces
    participant Auth as JWT Validator
    participant Mapper as Gen AI Mapper
    participant Kafka as Kafka
    participant CH as ClickHouse
    participant UI as PostHog UI

    App->>SDK: Make LLM API call
    SDK->>SDK: Create trace spans with gen_ai.* attributes

    alt Direct Export
        SDK->>CT: Export OTLP traces (gRPC/HTTP)
    else Via Collector
        SDK->>Coll: Export OTLP traces
        Coll->>Coll: Batch processing
        Coll->>CT: Forward OTLP traces
    end

    CT->>Auth: Validate JWT token
    Auth->>Auth: Extract team_id
    Auth-->>CT: team_id + validation result

    CT->>Mapper: Transform OTLP span
    Mapper->>Mapper: Parse gen_ai.* attributes
    Mapper->>Mapper: Map to $ai_* properties
    Mapper->>Mapper: Calculate cost
    Mapper->>Mapper: Build hierarchy
    Mapper-->>CT: PostHog event

    CT->>Kafka: Publish event
    Kafka->>CH: Write to events table

    UI->>CH: Query LLM analytics
    CH-->>UI: Return aggregated data
```

---

## Data Flow

### OTLP Trace to PostHog Event Flow

```mermaid
flowchart TD
    Start([OTLP Trace Received]) --> ValidateAuth{Valid JWT?}

    ValidateAuth -->|No| Reject[Reject: 401 Unauthorized]
    ValidateAuth -->|Yes| ExtractTeam[Extract team_id from JWT]

    ExtractTeam --> ParseSpan[Parse OTLP Span]
    ParseSpan --> ExtractAttrs[Extract Attributes]

    ExtractAttrs --> CheckGenAI{Has gen_ai.* attributes?}

    CheckGenAI -->|No| GenericSpan[Create generic $ai_span event]
    CheckGenAI -->|Yes| DetermineOp{Determine Operation Type}

    DetermineOp -->|chat/completion| GenEvent[Create $ai_generation event]
    DetermineOp -->|embedding| EmbedEvent[Create $ai_embedding event]
    DetermineOp -->|agent/chain| SpanEvent[Create $ai_span event]

    GenEvent --> MapAttributes[Map gen_ai.* → $ai_*]
    EmbedEvent --> MapAttributes
    SpanEvent --> MapAttributes
    GenericSpan --> MapAttributes

    MapAttributes --> ParseMessages{Message Format?}

    ParseMessages -->|JSON| ParseJSON[Parse gen_ai.prompt_json]
    ParseMessages -->|Flattened| ParseFlat[Parse gen_ai.prompt.N.*]

    ParseJSON --> ExtractUsage[Extract Token Usage]
    ParseFlat --> ExtractUsage

    ExtractUsage --> CalcCost[Calculate Cost]
    CalcCost --> LookupPricing[(Pricing DB)]
    LookupPricing --> ComputeCost[Compute USD cost]

    ComputeCost --> BuildHierarchy[Build Trace Hierarchy]
    BuildHierarchy --> CheckParent{Has parent_span_id?}

    CheckParent -->|Yes| LinkParent[Link to parent span]
    CheckParent -->|No| RootSpan[Mark as root span]

    LinkParent --> BuildEvent[Build PostHog Event]
    RootSpan --> BuildEvent

    BuildEvent --> AddMeta[Add Metadata]
    AddMeta --> AddTimestamp[Add timestamp, service name, etc.]

    AddTimestamp --> SerializeEvent[Serialize Event]
    SerializeEvent --> PublishKafka[Publish to Kafka]

    PublishKafka --> Success([Success: 200 OK])
    Reject --> End([End])
    Success --> End

    style ValidateAuth fill:#fff3cd
    style CheckGenAI fill:#d4edda
    style CalcCost fill:#e1f5ff
    style PublishKafka fill:#f8d7da
```

### Attribute Mapping Pipeline

```mermaid
flowchart LR
    subgraph "OTLP Span Attributes"
        A1[gen_ai.operation.name]
        A2[gen_ai.system]
        A3[gen_ai.request.model]
        A4[gen_ai.response.model]
        A5[gen_ai.prompt_json]
        A6[gen_ai.completion_json]
        A7[gen_ai.usage.input_tokens]
        A8[gen_ai.usage.output_tokens]
        A9[span.status.code]
        A10[trace_id]
        A11[span_id]
    end

    subgraph "Mapping Logic"
        M1[Operation Type Router]
        M2[Provider Normalizer]
        M3[Model Name Resolver]
        M4[Message Parser]
        M5[Token Counter]
        M6[Cost Calculator]
        M7[Error Handler]
        M8[ID Converter]
    end

    subgraph "PostHog Event Properties"
        P1[$ai_operation]
        P2[$ai_provider]
        P3[$ai_model]
        P4[$ai_input]
        P5[$ai_output_choices]
        P6[$ai_input_tokens]
        P7[$ai_output_tokens]
        P8[$ai_total_cost_usd]
        P9[$ai_is_error]
        P10[$ai_trace_id]
        P11[$ai_span_id]
    end

    A1 --> M1 --> P1
    A2 --> M2 --> P2
    A3 --> M3
    A4 --> M3
    M3 --> P3
    A5 --> M4 --> P4
    A6 --> M4 --> P5
    A7 --> M5 --> P6
    A8 --> M5 --> P7
    A7 --> M6
    A8 --> M6
    P3 --> M6
    M6 --> P8
    A9 --> M7 --> P9
    A10 --> M8 --> P10
    A11 --> M8 --> P11

    style M1 fill:#e1f5ff
    style M4 fill:#e1f5ff
    style M6 fill:#e1f5ff
```

---

## Component Details

### capture-traces Service Architecture

```mermaid
graph TB
    subgraph "capture-traces Service"
        subgraph "HTTP Server Layer"
            HTTPServer[Axum HTTP Server]
            GRPCServer[Tonic gRPC Server]
            HealthEndpoint[Health Check]
            MetricsEndpoint[Prometheus Metrics]
        end

        subgraph "Request Processing"
            OTLPDecoder[OTLP Decoder]
            RateLimiter[Rate Limiter]
            AuthMiddleware[Auth Middleware]
        end

        subgraph "Core Logic"
            SpanParser[Span Parser]
            GenAIMapper[Gen AI Attribute Mapper]
            CostCalculator[Cost Calculator]
            HierarchyBuilder[Hierarchy Builder]
        end

        subgraph "Data Access"
            PricingCache[Pricing Cache]
            TeamCache[Team ID Cache]
        end

        subgraph "Output"
            EventSerializer[Event Serializer]
            KafkaProducer[Kafka Producer]
            ErrorHandler[Error Handler]
        end
    end

    HTTPServer --> OTLPDecoder
    GRPCServer --> OTLPDecoder

    OTLPDecoder --> RateLimiter
    RateLimiter --> AuthMiddleware

    AuthMiddleware --> SpanParser
    SpanParser --> GenAIMapper

    GenAIMapper --> CostCalculator
    GenAIMapper --> HierarchyBuilder

    CostCalculator --> PricingCache
    AuthMiddleware --> TeamCache

    CostCalculator --> EventSerializer
    HierarchyBuilder --> EventSerializer

    EventSerializer --> KafkaProducer

    KafkaProducer --> ErrorHandler

    HealthEndpoint -.-> HTTPServer
    MetricsEndpoint -.-> HTTPServer

    style GenAIMapper fill:#e1f5ff
    style CostCalculator fill:#e1f5ff
    style KafkaProducer fill:#f8d7da
```

### Gen AI Mapper Module

```mermaid
classDiagram
    class GenAIMapper {
        +map_span_to_event(span: Span) Event
        -determine_event_type(span: Span) EventType
        -extract_messages(span: Span) Messages
        -parse_json_messages(json: String) Messages
        -parse_flattened_messages(attrs: HashMap) Messages
        -extract_tools(span: Span) Tools
        -calculate_cost(span: Span) f64
        -build_hierarchy_info(span: Span) HierarchyInfo
    }

    class Span {
        +trace_id: Vec~u8~
        +span_id: Vec~u8~
        +parent_span_id: Vec~u8~
        +name: String
        +attributes: HashMap~String, AnyValue~
        +start_time: u64
        +end_time: u64
        +status: SpanStatus
    }

    class Event {
        +event: String
        +distinct_id: String
        +team_id: i64
        +properties: HashMap~String, Value~
        +timestamp: DateTime
    }

    class MessageParser {
        +parse_json(json: String) Vec~Message~
        +parse_flattened(attrs: HashMap, prefix: String) Vec~Message~
        -extract_role(attrs: HashMap, index: i32) String
        -extract_content(attrs: HashMap, index: i32) String
        -extract_tool_calls(attrs: HashMap, index: i32) Vec~ToolCall~
    }

    class CostCalculator {
        +calculate(model: String, tokens: TokenUsage) f64
        -get_pricing(model: String) Pricing
        -normalize_model_name(model: String) String
    }

    class HierarchyBuilder {
        +build(span: Span, siblings: Vec~Span~) HierarchyInfo
        -find_parent(span: Span) Option~Span~
        -find_children(span: Span) Vec~Span~
        -calculate_depth(span: Span) u32
    }

    GenAIMapper --> MessageParser
    GenAIMapper --> CostCalculator
    GenAIMapper --> HierarchyBuilder
    GenAIMapper --> Span
    GenAIMapper --> Event
```

---

## Authentication & Security

### JWT Authentication Flow

```mermaid
sequenceDiagram
    participant Client as LLM Application
    participant PostHog as PostHog API
    participant CT as capture-traces
    participant Cache as Token Cache
    participant DB as PostgreSQL

    Note over Client,PostHog: Initial Setup (one-time)
    Client->>PostHog: Request JWT token
    PostHog->>PostHog: Generate JWT with team_id
    PostHog-->>Client: Return JWT token

    Note over Client,CT: Per-Request Flow
    Client->>CT: OTLP Request + Bearer JWT
    CT->>CT: Extract JWT from header

    CT->>Cache: Check token cache

    alt Token in cache
        Cache-->>CT: team_id + validation
    else Token not in cache
        CT->>CT: Decode JWT
        CT->>CT: Verify signature (HMAC-SHA256)
        CT->>CT: Check expiration

        alt Valid token
            CT->>CT: Extract team_id claim
            CT->>DB: Validate team exists
            DB-->>CT: Team validation result
            CT->>Cache: Store in cache (15 min TTL)
            Cache-->>CT: team_id
        else Invalid token
            CT-->>Client: 401 Unauthorized
        end
    end

    CT->>CT: Process request with team_id
    CT-->>Client: 200 OK
```

### Security Layers

```mermaid
graph TB
    subgraph "Security Layers"
        L1[TLS/HTTPS Transport]
        L2[JWT Authentication]
        L3[Rate Limiting]
        L4[Team Isolation]
        L5[Input Validation]
        L6[Output Sanitization]
    end

    Request[Incoming Request] --> L1
    L1 --> L2
    L2 --> L3
    L3 --> L4
    L4 --> L5
    L5 --> Process[Process Request]
    Process --> L6
    L6 --> Response[Send Response]

    L2 -.-> TokenCache[(Token Cache)]
    L3 -.-> RateLimitStore[(Rate Limit Store)]
    L4 -.-> TeamDB[(Team Database)]

    style L1 fill:#d4edda
    style L2 fill:#d4edda
    style L3 fill:#fff3cd
    style L4 fill:#d4edda
```

---

## Message Transformation Pipeline

### Prompt Message Extraction

```mermaid
flowchart TD
    Start([Extract Messages from Span]) --> CheckFormat{Check Format}

    CheckFormat -->|JSON format| JSONPath[Check gen_ai.prompt_json]
    CheckFormat -->|Flattened format| FlatPath[Check gen_ai.prompt.0.*]
    CheckFormat -->|Events format| EventPath[Check span events]

    JSONPath --> ParseJSON{Parse JSON}
    ParseJSON -->|Success| JSONArray[JSON Array of Messages]
    ParseJSON -->|Fail| FallbackFlat[Try flattened format]

    FlatPath --> IterateFlat[Iterate indices 0..N]
    IterateFlat --> ExtractRole[Extract gen_ai.prompt.N.role]
    ExtractRole --> ExtractContent[Extract gen_ai.prompt.N.content]
    ExtractContent --> ExtractToolCalls[Extract gen_ai.prompt.N.tool_calls]
    ExtractToolCalls --> BuildMessage[Build Message object]
    BuildMessage --> MoreMessages{More messages?}
    MoreMessages -->|Yes| IterateFlat
    MoreMessages -->|No| FlatArray[Array of Messages]

    EventPath --> FilterEvents[Filter gen_ai events]
    FilterEvents --> ExtractEventData[Extract message data]
    ExtractEventData --> EventArray[Array of Messages]

    FallbackFlat --> IterateFlat

    JSONArray --> Normalize[Normalize Message Format]
    FlatArray --> Normalize
    EventArray --> Normalize

    Normalize --> ValidateMessages{Validate}
    ValidateMessages -->|Valid| CleanMessages[Clean & Sanitize]
    ValidateMessages -->|Invalid| EmptyArray[Return empty array]

    CleanMessages --> TruncateIfNeeded{Check Length}
    TruncateIfNeeded -->|Too long| TruncateContent[Truncate content]
    TruncateIfNeeded -->|OK| FinalArray[Final Message Array]

    TruncateContent --> FinalArray

    FinalArray --> Success([Return Messages])
    EmptyArray --> Success

    style ParseJSON fill:#e1f5ff
    style Normalize fill:#e1f5ff
    style CleanMessages fill:#d4edda
```

### Cost Calculation Pipeline

```mermaid
flowchart LR
    subgraph "Input"
        Model[Model Name]
        InputTokens[Input Tokens]
        OutputTokens[Output Tokens]
    end

    subgraph "Processing"
        NormalizeName[Normalize Model Name]
        LookupPricing[Lookup Pricing]
        CheckCache{In Cache?}
        FetchPricing[(Pricing Database)]
        CalcInputCost[Calculate Input Cost]
        CalcOutputCost[Calculate Output Cost]
        Sum[Sum Costs]
        Round[Round to 6 decimals]
    end

    subgraph "Output"
        TotalCost[Total Cost USD]
    end

    Model --> NormalizeName
    NormalizeName --> LookupPricing
    LookupPricing --> CheckCache

    CheckCache -->|Hit| PricingData[Pricing Data]
    CheckCache -->|Miss| FetchPricing
    FetchPricing --> PricingData

    PricingData --> CalcInputCost
    PricingData --> CalcOutputCost

    InputTokens --> CalcInputCost
    OutputTokens --> CalcOutputCost

    CalcInputCost --> Sum
    CalcOutputCost --> Sum

    Sum --> Round
    Round --> TotalCost

    style NormalizeName fill:#e1f5ff
    style CheckCache fill:#fff3cd
    style Sum fill:#e1f5ff
```

---

## Deployment Architecture

### Development Environment

```mermaid
graph TB
    subgraph "Developer Machine"
        IDE[IDE/Editor]
        LocalOTEL[Local OTEL App]
    end

    subgraph "Docker Compose"
        OTELCol[OTEL Collector]
        CapTraces[capture-traces]
        CapLogs[capture-logs]
        Kafka[Kafka]
        Zookeeper[Zookeeper]
        CH[ClickHouse]
        PG[(PostgreSQL)]
        Redis[(Redis)]
        Django[Django App]
    end

    IDE --> LocalOTEL
    LocalOTEL --> OTELCol

    OTELCol --> CapTraces
    OTELCol --> CapLogs

    CapTraces --> Kafka
    CapLogs --> Kafka

    Kafka --> Zookeeper
    Kafka --> CH

    Django --> PG
    Django --> Redis
    Django --> CH

    style CapTraces fill:#e1f5ff
    style CapLogs fill:#d4edda
```

### Production Deployment (Kubernetes)

```mermaid
graph TB
    subgraph "Internet"
        Client[Client Applications]
        LB[Load Balancer]
    end

    subgraph "Kubernetes Cluster"
        subgraph "Ingress"
            Ingress[Nginx Ingress]
        end

        subgraph "OTEL Services"
            CTDeploy[capture-traces Deployment]
            CT1[Pod 1]
            CT2[Pod 2]
            CT3[Pod 3]
            CTHPA[HPA: 2-10 replicas]

            CLDeploy[capture-logs Deployment]
            CL1[Pod 1]
            CL2[Pod 2]
        end

        subgraph "Message Queue"
            KafkaCluster[Kafka StatefulSet]
            K1[Broker 1]
            K2[Broker 2]
            K3[Broker 3]
        end

        subgraph "Storage"
            CHCluster[ClickHouse Cluster]
            CH1[Node 1]
            CH2[Node 2]
            CH3[Node 3]
        end

        subgraph "Config & Secrets"
            ConfigMap[ConfigMap]
            Secrets[Secrets]
        end

        subgraph "Monitoring"
            Prometheus[Prometheus]
            Grafana[Grafana]
        end
    end

    Client --> LB
    LB --> Ingress

    Ingress --> CTDeploy
    CTDeploy --> CT1
    CTDeploy --> CT2
    CTDeploy --> CT3
    CTHPA -.Scale.-> CTDeploy

    Ingress --> CLDeploy
    CLDeploy --> CL1
    CLDeploy --> CL2

    CT1 --> KafkaCluster
    CT2 --> KafkaCluster
    CT3 --> KafkaCluster

    KafkaCluster --> K1
    KafkaCluster --> K2
    KafkaCluster --> K3

    K1 --> CHCluster
    K2 --> CHCluster
    K3 --> CHCluster

    CHCluster --> CH1
    CHCluster --> CH2
    CHCluster --> CH3

    ConfigMap --> CTDeploy
    ConfigMap --> CLDeploy
    Secrets --> CTDeploy
    Secrets --> CLDeploy

    CT1 -.Metrics.-> Prometheus
    CT2 -.Metrics.-> Prometheus
    CT3 -.Metrics.-> Prometheus

    Prometheus --> Grafana

    style CTDeploy fill:#e1f5ff
    style CTHPA fill:#fff3cd
    style KafkaCluster fill:#f8d7da
```

### Scalability Model

```mermaid
graph LR
    subgraph "Load Patterns"
        Low[Low Load<br/>< 100 req/s]
        Medium[Medium Load<br/>100-1000 req/s]
        High[High Load<br/>> 1000 req/s]
    end

    subgraph "Scaling Strategy"
        HPA[Horizontal Pod Autoscaling]
        VPA[Vertical Pod Autoscaling]
        KafkaPartitions[Kafka Partition Increase]
        CHSharding[ClickHouse Sharding]
    end

    subgraph "Resource Allocation"
        R1["capture-traces:<br/>2 pods<br/>500m CPU / 512Mi RAM"]
        R2["capture-traces:<br/>5 pods<br/>1000m CPU / 1Gi RAM"]
        R3["capture-traces:<br/>10 pods<br/>2000m CPU / 2Gi RAM"]
    end

    Low --> HPA
    Medium --> HPA
    High --> HPA
    High --> VPA
    High --> KafkaPartitions
    High --> CHSharding

    HPA --> R1
    HPA --> R2
    HPA --> R3

    style Low fill:#d4edda
    style Medium fill:#fff3cd
    style High fill:#f8d7da
```

---

## Integration Patterns

### Pattern 1: Direct Export (Simplest)

```mermaid
sequenceDiagram
    participant App as Application
    participant SDK as OTEL SDK
    participant CT as capture-traces
    participant Kafka as Kafka
    participant CH as ClickHouse

    Note over App,SDK: No OTEL Collector needed

    App->>SDK: Configure exporter endpoint
    SDK->>SDK: Set endpoint to capture-traces
    SDK->>SDK: Set JWT in headers

    loop For each LLM call
        App->>App: Make LLM API call
        App->>SDK: SDK auto-instruments
        SDK->>CT: Export span via OTLP
        CT->>Kafka: Publish event
        Kafka->>CH: Consume & write
    end

    Note over SDK,CT: Direct connection<br/>Lower latency<br/>Fewer moving parts
```

### Pattern 2: Collector-Based (Recommended for Production)

```mermaid
sequenceDiagram
    participant App as Application
    participant SDK as OTEL SDK
    participant Coll as OTEL Collector
    participant CT as capture-traces
    participant CL as capture-logs
    participant Kafka as Kafka

    Note over App,Coll: Collector provides buffering,<br/>batching, and routing

    App->>SDK: Configure exporter to Collector
    SDK->>SDK: Set endpoint to localhost:4317

    loop For each LLM call
        App->>App: Make LLM API call
        App->>SDK: SDK auto-instruments
        SDK->>Coll: Export span (local)
        Coll->>Coll: Buffer & batch spans
        Coll->>Coll: Apply sampling rules
        Coll->>CT: Export traces
        Coll->>CL: Export logs
        CT->>Kafka: Publish events
        CL->>Kafka: Publish logs
    end

    Note over Coll,Kafka: Collector benefits:<br/>- Batching<br/>- Retry logic<br/>- Multiple destinations<br/>- Sampling
```

### Pattern 3: Multi-Service Tracing

```mermaid
graph LR
    subgraph "Service A: Frontend"
        A1[User Request]
        A2[OTEL Context]
        A3[trace_id: ABC123]
    end

    subgraph "Service B: API"
        B1[Receive Request]
        B2[Extract Context]
        B3[LLM Call]
        B4[parent_span_id: from A]
    end

    subgraph "Service C: LLM Provider"
        C1[OpenAI API]
        C2[Generate Response]
    end

    subgraph "PostHog"
        P1[capture-traces]
        P2[Events with hierarchy]
    end

    A1 --> A2
    A2 --> A3
    A3 -->|HTTP Header| B1
    B1 --> B2
    B2 --> B3
    B3 --> C1
    C1 --> C2
    B3 --> B4
    B4 -->|OTLP| P1
    A3 -->|OTLP| P1
    P1 --> P2

    Note1[Full trace across<br/>multiple services<br/>with parent-child<br/>relationships]

    style B3 fill:#e1f5ff
    style P2 fill:#d4edda
```

### Pattern 4: Framework-Specific Auto-Instrumentation

```mermaid
graph TB
    subgraph "LangChain Application"
        LC1[LangChain Code]
        LC2[Chain Execution]
        LC3[LLM Calls]
    end

    subgraph "OTEL Instrumentation Layer"
        OI1[LangChain Instrumentor]
        OI2[OpenAI Instrumentor]
        OI3[Context Propagation]
    end

    subgraph "Span Generation"
        S1[Chain Span]
        S2[LLM Call Span]
        S3[Tool Call Span]
    end

    subgraph "PostHog"
        PH1[capture-traces]
        PH2[$ai_trace event]
        PH3[$ai_generation events]
        PH4[$ai_span events]
    end

    LC1 --> LC2
    LC2 --> LC3

    LC2 -.Auto-instrument.-> OI1
    LC3 -.Auto-instrument.-> OI2

    OI1 --> S1
    OI2 --> S2
    OI1 --> S3

    OI3 -.Links spans.-> S1
    OI3 -.Links spans.-> S2
    OI3 -.Links spans.-> S3

    S1 --> PH1
    S2 --> PH1
    S3 --> PH1

    PH1 --> PH2
    PH1 --> PH3
    PH1 --> PH4

    style OI1 fill:#e1f5ff
    style OI2 fill:#e1f5ff
    style PH1 fill:#d4edda
```

---

## Performance Considerations

### Request Processing Pipeline

```mermaid
graph LR
    subgraph "Latency Budget (Target: < 100ms p99)"
        L1["Network: 10ms"]
        L2["Auth: 5ms"]
        L3["Parsing: 20ms"]
        L4["Mapping: 30ms"]
        L5["Kafka: 25ms"]
        L6["Buffer: 10ms"]
    end

    Request[Request] --> L1
    L1 --> L2
    L2 --> L3
    L3 --> L4
    L4 --> L5
    L5 --> L6
    L6 --> Response[Response]

    style L3 fill:#e1f5ff
    style L4 fill:#e1f5ff
    style L5 fill:#f8d7da
```

### Optimization Strategies

```mermaid
mindmap
  root((Performance<br/>Optimization))
    Caching
      JWT token cache
      Pricing data cache
      Team metadata cache
    Batching
      Batch Kafka writes
      Batch span processing
      Collector batching
    Async Processing
      Non-blocking I/O
      Async Kafka producer
      Background workers
    Resource Management
      Connection pooling
      Memory limits
      CPU quotas
    Monitoring
      Latency tracking
      Error rates
      Queue depths
      Resource usage
```

---

## Error Handling

### Error Propagation Flow

```mermaid
flowchart TD
    Start([Request Received]) --> TryAuth{Try Auth}

    TryAuth -->|Error| AuthError[Auth Error]
    TryAuth -->|Success| TryParse{Try Parse OTLP}

    AuthError --> Log401[Log error]
    Log401 --> Return401[Return 401]

    TryParse -->|Error| ParseError[Parse Error]
    TryParse -->|Success| TryMap{Try Map Attributes}

    ParseError --> Log400[Log error]
    Log400 --> Return400[Return 400]

    TryMap -->|Error| MapError[Mapping Error]
    TryMap -->|Success| TryKafka{Try Kafka Publish}

    MapError --> LogWarn[Log warning]
    LogWarn --> BestEffort[Create best-effort event]
    BestEffort --> TryKafka

    TryKafka -->|Error| KafkaError[Kafka Error]
    TryKafka -->|Success| Success[Success]

    KafkaError --> Retry{Retry?}
    Retry -->|Yes| BackoffWait[Exponential backoff]
    BackoffWait --> TryKafka
    Retry -->|No| Log503[Log error]
    Log503 --> Return503[Return 503]

    Success --> Return200[Return 200]

    Return401 --> End([End])
    Return400 --> End
    Return503 --> End
    Return200 --> End

    style AuthError fill:#f8d7da
    style ParseError fill:#f8d7da
    style KafkaError fill:#f8d7da
    style BestEffort fill:#fff3cd
```

---

## Monitoring & Observability

### Metrics Collection

```mermaid
graph TB
    subgraph "capture-traces Service"
        App[Application Logic]
    end

    subgraph "Prometheus Metrics"
        M1[http_requests_total]
        M2[http_request_duration_seconds]
        M3[otlp_spans_received_total]
        M4[otlp_spans_processed_total]
        M5[otlp_spans_dropped_total]
        M6[genai_events_created_total]
        M7[kafka_publish_duration_seconds]
        M8[cost_calculation_duration_seconds]
        M9[auth_cache_hit_total]
        M10[auth_cache_miss_total]
    end

    subgraph "Prometheus"
        Prom[Prometheus Server]
        Scrape[Metrics Scraper]
    end

    subgraph "Visualization"
        Grafana[Grafana Dashboards]
        Alerts[Alertmanager]
    end

    App --> M1
    App --> M2
    App --> M3
    App --> M4
    App --> M5
    App --> M6
    App --> M7
    App --> M8
    App --> M9
    App --> M10

    Scrape --> M1
    Scrape --> M2
    Scrape --> M3
    Scrape --> M4
    Scrape --> M5
    Scrape --> M6
    Scrape --> M7
    Scrape --> M8
    Scrape --> M9
    Scrape --> M10

    Scrape --> Prom
    Prom --> Grafana
    Prom --> Alerts

    style M6 fill:#e1f5ff
    style M8 fill:#e1f5ff
```

### Health Check System

```mermaid
sequenceDiagram
    participant K8s as Kubernetes
    participant CT as capture-traces
    participant Kafka as Kafka
    participant Cache as Redis

    Note over K8s,CT: Liveness Probe (every 10s)
    K8s->>CT: GET /_liveness
    CT->>CT: Check process alive
    CT-->>K8s: 200 OK or Timeout

    Note over K8s,CT: Readiness Probe (every 5s)
    K8s->>CT: GET /_readiness
    CT->>Kafka: Check connection
    Kafka-->>CT: Connected
    CT->>Cache: Check connection
    Cache-->>CT: Connected
    CT-->>K8s: 200 OK

    Note over K8s,CT: If readiness fails
    CT-->>K8s: 503 Service Unavailable
    K8s->>K8s: Remove from load balancer
    K8s->>K8s: Wait for recovery
```

---

## Appendix: Configuration Examples

### capture-traces Environment Variables

```yaml
# Service Configuration
HOST: "0.0.0.0"
PORT: "4318"
GRPC_PORT: "4317"
SERVICE_NAME: "capture-traces"

# Authentication
JWT_SECRET: "${JWT_SECRET}"
JWT_ALGORITHM: "HS256"
TOKEN_CACHE_TTL_SECONDS: "900"  # 15 minutes

# Kafka Configuration
KAFKA_HOSTS: "kafka:9092"
KAFKA_TOPIC: "events_plugin_ingestion"
KAFKA_COMPRESSION: "snappy"
KAFKA_BATCH_SIZE: "100"
KAFKA_LINGER_MS: "100"

# Performance
MAX_CONCURRENT_REQUESTS: "1000"
REQUEST_TIMEOUT_MS: "30000"
WORKER_THREADS: "4"

# Rate Limiting
RATE_LIMIT_PER_SECOND: "1000"
RATE_LIMIT_BURST: "2000"

# Caching
PRICING_CACHE_TTL_SECONDS: "3600"  # 1 hour
TEAM_CACHE_TTL_SECONDS: "300"      # 5 minutes

# Monitoring
PROMETHEUS_PORT: "9090"
LOG_LEVEL: "info"
LOG_FORMAT: "json"

# Feature Flags
ENABLE_COST_CALCULATION: "true"
ENABLE_HIERARCHY_BUILDING: "true"
ENABLE_MESSAGE_TRUNCATION: "true"
MAX_MESSAGE_LENGTH: "100000"
```

---

**Document Version**: 1.0
**Last Updated**: November 13, 2025
**Related Documents**: [OTEL_GENAI_RESEARCH.md](./OTEL_GENAI_RESEARCH.md)
