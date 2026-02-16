# Multi-Threaded Ingestion Prototype

## Architecture Overview

The current ingestion pipeline runs in a single Node.js process: one event loop consuming from Kafka, parsing messages, resolving teams, processing persons, and writing to ClickHouse. This prototype splits the pipeline into two components:

```text
                                    ┌──────────────────────┐
                                    │  ingestion-api-1     │
                                    │  (Node.js :3400)     │
                                    ├──────────────────────┤
┌─────────────┐   ┌──────────────┐  │  ingestion-api-2     │
│   Kafka     │──▶│  ingestion   │──│  (Node.js :3401)     │
│   topics    │   │  consumer    │  ├──────────────────────┤
└─────────────┘   │  (Rust)      │  │  ingestion-api-3     │
                  └──────────────┘  │  (Node.js :3402)     │
                                    ├──────────────────────┤
                                    │  ingestion-api-4     │
                                    │  (Node.js :3403)     │
                                    └──────────────────────┘
```

**Rust Ingestion Consumer**: Subscribes to Kafka, extracts `token` and `distinct_id` from message headers, uses consistent hashing to route messages to a fixed set of Node.js ingestion API processes. Manages Kafka offset commits.

**Node.js Ingestion API**: Accepts batches of messages via HTTP, converts them to the `Message` type, feeds them through the existing `JoinedIngestionPipeline`, and returns 200 OK on completion.

## Why This Architecture

1. **CPU-bound work parallelized**: Person processing, group resolution, and event writing are distributed across multiple Node.js processes
2. **Consistent routing**: Events for the same `token:distinct_id` always go to the same process, preserving the sequential-per-distinct-id invariant the pipeline requires
3. **Kafka offset safety**: The Rust consumer only commits offsets after all API processes acknowledge their batches
4. **Incremental**: The Node.js processes reuse the existing pipeline; only the Kafka consumption layer changes

## Components

### 1. Rust Ingestion Consumer (`rust/ingestion-consumer/`)

New Rust project in the workspace. Responsibilities:

- Subscribe to `events_plugin_ingestion` (and optionally overflow/historical topics)
- For each message batch from Kafka:
  1. Extract `token` and `distinct_id` from Kafka headers
  2. Hash `token:distinct_id` to determine target ingestion API process
  3. Group messages by target process
  4. Send each group as an HTTP POST to the corresponding process
  5. Wait for all responses (200 OK)
  6. Commit Kafka offsets

**Key design**: The consumer does NOT parse message bodies. It only reads headers for routing and forwards raw message bytes.

**Configuration** (via environment variables):

- `KAFKA_HOSTS` - Kafka broker addresses
- `KAFKA_TOPIC` - Topic to consume (default: `events_plugin_ingestion`)
- `KAFKA_GROUP_ID` - Consumer group (default: `ingestion-consumer-rust`)
- `INGESTION_API_ADDRESSES` - Comma-separated list of ingestion API addresses (e.g., `http://localhost:3400,http://localhost:3401,http://localhost:3402,http://localhost:3403`)
- `BATCH_TIMEOUT_MS` - Max time to wait for a batch (default: `500`)
- `BATCH_SIZE` - Max messages per batch (default: `500`)

**Consistent hashing**: Uses the same `token:distinct_id` key the pipeline uses for groupBy. A simple modulo hash over the number of API processes (for the prototype; can be upgraded to consistent hashing ring later).

### 2. Node.js Ingestion API (new capability in `nodejs/`)

New server mode/capability: `ingestionApi`. When enabled, the process:

1. Does NOT subscribe to Kafka
2. Sets up the full `JoinedIngestionPipeline` (same as `IngestionConsumer`)
3. Exposes an HTTP endpoint: `POST /ingest`
4. On each request:
   - Parses the JSON request body (array of serialized Kafka messages)
   - Converts each to a `Message` object (compatible with node-rdkafka `Message`)
   - Calls `handleKafkaBatch(messages)` (reuses existing pipeline)
   - Returns `200 OK` with `{ "status": "ok" }`

**Message format** (JSON, designed for easy gRPC migration):

```json
{
  "messages": [
    {
      "topic": "events_plugin_ingestion",
      "partition": 0,
      "offset": 12345,
      "timestamp": 1708012800000,
      "key": "base64-encoded-key-or-null",
      "value": "base64-encoded-message-body",
      "headers": [{ "token": "phc_abc123" }, { "distinct_id": "user-456" }]
    }
  ]
}
```

The `headers` field preserves the Kafka `MessageHeader[]` format (array of single-key objects).

### 3. Transport Abstraction

Both Rust and Node.js define an abstraction over the transport:

**Rust** (`ingestion-consumer/src/transport.rs`):

```rust
#[async_trait]
pub trait IngestionTransport: Send + Sync {
    async fn send_batch(&self, address: &str, messages: Vec<RawKafkaMessage>) -> Result<()>;
}
```

**Node.js** (`nodejs/src/ingestion/api/transport.ts`):

```typescript
export interface IngestBatchRequest {
  messages: SerializedKafkaMessage[]
}

export interface SerializedKafkaMessage {
  topic: string
  partition: number
  offset: number
  timestamp?: number
  key: string | null // base64
  value: string | null // base64
  headers: Record<string, string>[] // preserves Kafka MessageHeader format
}
```

This abstraction makes it straightforward to swap JSON for gRPC later.

### 4. mprocs Configuration

New entries in `bin/mprocs.yaml`:

```yaml
ingestion-consumer:
  shell: |-
    bin/wait-for-docker && \
    bin/start-rust-service ingestion-consumer
  capability: multi_thread_ingestion

ingestion-1:
  shell: |-
    bin/wait-for-docker && \
    PLUGIN_SERVER_MODE=ingestion_api \
    INGESTION_API_PORT=3400 \
    ./bin/posthog-node
  capability: multi_thread_ingestion

ingestion-2:
  shell: |-
    bin/wait-for-docker && \
    PLUGIN_SERVER_MODE=ingestion_api \
    INGESTION_API_PORT=3401 \
    ./bin/posthog-node
  capability: multi_thread_ingestion

ingestion-3:
  shell: |-
    bin/wait-for-docker && \
    PLUGIN_SERVER_MODE=ingestion_api \
    INGESTION_API_PORT=3402 \
    ./bin/posthog-node
  capability: multi_thread_ingestion

ingestion-4:
  shell: |-
    bin/wait-for-docker && \
    PLUGIN_SERVER_MODE=ingestion_api \
    INGESTION_API_PORT=3403 \
    ./bin/posthog-node
  capability: multi_thread_ingestion
```

Port range: **3400-3403** (clear of existing services: capture=3307, feature-flags=3001, cyclotron=3303/3304, cymbal=3302, embedding=3305, batch-import=3301, capture-replay=3306, capture-ai=3309).

### 5. Message Flow (Detailed)

```text
1. Kafka produces message with headers:
   { token: "phc_abc", distinct_id: "user-1", ... }

2. Rust consumer receives batch of N messages

3. For each message:
   a. Read token header (fallback: "")
   b. Read distinct_id header (fallback: "")
   c. Compute hash("phc_abc:user-1") % 4 = target process index

4. Group messages by target index:
   { 0: [msg1, msg5], 1: [msg2], 2: [msg3, msg4], 3: [] }

5. Send HTTP POST to each non-empty group concurrently:
   POST http://localhost:3400/ingest  { messages: [msg1, msg5] }
   POST http://localhost:3401/ingest  { messages: [msg2] }
   POST http://localhost:3402/ingest  { messages: [msg3, msg4] }

6. All return 200 OK

7. Rust consumer stores offsets and commits
```

## API Contract

### POST /ingest

**Request**:

```http
Content-Type: application/json

{
  "messages": [
    {
      "topic": "events_plugin_ingestion",
      "partition": 0,
      "offset": 12345,
      "timestamp": 1708012800000,
      "key": "<base64-or-null>",
      "value": "<base64-encoded-body>",
      "headers": [
        { "token": "phc_abc123" },
        { "distinct_id": "user-456" },
        { "uuid": "..." }
      ]
    }
  ]
}
```

**Response (success)**:

```http
HTTP 200 OK
Content-Type: application/json

{ "status": "ok" }
```

**Response (error)**:

```http
HTTP 500 Internal Server Error
Content-Type: application/json

{ "status": "error", "message": "pipeline failed: ..." }
```

The Rust consumer treats any non-200 response as a failure and will not commit offsets for that batch. It will retry after a backoff.

## Error Handling

- **Node.js process crashes**: The Rust consumer will get a connection error. It stops committing offsets. Kafka will rebalance after session timeout. mprocs auto-restarts the Node.js process.
- **Slow Node.js process**: The Rust consumer waits for all processes before committing. Backpressure propagates naturally.
- **Rust consumer crashes**: Kafka consumer group rebalances. mprocs auto-restarts.
- **Poison pill messages**: The Node.js pipeline already has DLQ handling. Errors are contained per-message within the pipeline.

## Implementation Plan (Commit-by-Commit)

### Commit 1: Architecture documentation

- Add this document

### Commit 2: Node.js transport types and ingestion API server

- Add `SerializedKafkaMessage` and `IngestBatchRequest` types
- Add `deserializeKafkaMessages()` function to convert from API format to `Message`
- Add `IngestionApiServer` class:
  - Sets up express routes
  - Initializes the `JoinedIngestionPipeline` (reuses `IngestionConsumer` setup)
  - Handles `POST /ingest` requests
- Add `ingestionApi` capability and `PLUGIN_SERVER_MODE`
- Wire into `server.ts`
- **Tests**:
  - Unit tests for `deserializeKafkaMessages()` (round-trip serialization)
  - Unit tests for header parsing from serialized format
  - Integration test for `POST /ingest` endpoint (mock pipeline)

### Commit 3: Rust ingestion consumer project

- Create `rust/ingestion-consumer/` with Cargo.toml
- Add to workspace
- Implement:
  - `config.rs` - Environment-based configuration
  - `transport.rs` - `IngestionTransport` trait + `JsonTransport` implementation (reqwest)
  - `router.rs` - Message routing logic (extract headers, hash, group by target)
  - `consumer.rs` - Main consumer loop (Kafka consume -> route -> send -> commit)
  - `main.rs` - Entry point with tracing, health check
- Add to `bin/start-rust-service`
- **Tests**:
  - Unit tests for routing logic (consistent hash distribution)
  - Unit tests for header extraction
  - Unit tests for message serialization (JSON format matches Node.js expectations)
  - Integration test with mock HTTP server

### Commit 4: mprocs and dev environment integration

- Add mprocs entries for `ingestion-consumer`, `ingestion-1` through `ingestion-4`
- Add `multi_thread_ingestion` capability to `devenv/intent-map.yaml`
- Add `multi_thread_ingestion` intent
- Ensure the regular `nodejs` process still works (these are separate, opt-in)

### Commit 5: End-to-end test and polish

- Add a simple end-to-end test script that:
  - Starts 1 Rust consumer + 4 Node.js ingestion API processes
  - Produces test events to Kafka
  - Verifies events appear in ClickHouse
- Fix any issues found during integration
- Add metrics (batch size, latency, errors per process)

## Future Work (Not in Prototype)

- gRPC transport (replace JSON with protobuf for lower overhead)
- Dynamic scaling (add/remove ingestion API processes)
- Consistent hashing ring (handle process failures gracefully)
- Weighted routing (based on process load)
- Multiple Kafka topics (overflow, historical)
- Production deployment configuration
