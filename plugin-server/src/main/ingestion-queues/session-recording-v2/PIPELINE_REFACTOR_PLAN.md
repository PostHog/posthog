# Session Recording Consumer Pipeline Refactor Plan

## Overview

Refactor the session recording consumer to use the pipeline pattern from the ingestion consumer. This will improve code organization, testability, and maintainability by separating concerns into discrete pipeline steps.

---

## Current Flow

The session recording consumer currently processes messages in `consumer.ts:199-238`:

1. **Collect batch metrics** → Track batch size and KB
2. **Collect message metrics** → Track individual message metrics
3. **Apply restrictions** → Filter/redirect messages to overflow based on restrictions
4. **Parse batch** → Decompress, validate JSON, extract snapshot data
5. **Filter by team** → Validate team exists, check retention period
6. **Monitor lib versions** → Track client library versions, emit warnings
7. **Process messages** → Obtain batch recorder and record events
8. **Flush if needed** → Write to S3 and metadata stores

---

## Pipeline Steps

### Step 0: Collect Metrics

- **Type**: Batch-level operation (first step)
- **Input**: `{ message: Message }[]`
- **Output**: `{ message: Message }[]`
- **Operations**:
    - Calculate batch size (number of messages)
    - Calculate batch size in KB
    - Call `SessionRecordingIngesterMetrics.observeKafkaBatchSize(batchSize)`
    - Call `SessionRecordingIngesterMetrics.observeKafkaBatchSizeKb(batchSizeKb)`
    - Aggregate per-partition message counts
    - Call `SessionRecordingIngesterMetrics.incrementMessageReceived(partition, count)` for each partition
- **Note**: Metrics are NOT treated as side effects. Both batch-level and per-message metrics are collected in this single step.
- **Status**: ✅ Implemented and tested
- **File**: `steps/collect-batch-metrics.ts`

### Step 1: Parse Headers

- **Type**: Per-message, sequential
- **Input**: `{ message: Message }`
- **Output**: `{ message: Message, headers: EventHeaders }`
- **Operations**:
    - Parse headers from message to extract token/distinct_id
    - Call `parseEventHeaders(message.headers)`
- **Note**: Required before applying restrictions since we need token/distinct_id
- **Status**: ✅ Implemented and tested
- **File**: `steps/parse-headers.ts`

### Step 2: Apply Restrictions

- **Type**: Per-message, sequential
- **Input**: `{ message: Message, headers: EventHeaders }`
- **Output**: `{ message: Message, headers: EventHeaders }`
- **Operations**:
    - **Step 2a**: Drop if `shouldDropEvent(token, distinct_id)` - `apply-drop-restrictions.ts`
    - **Step 2b**: Redirect to overflow if `shouldForceOverflow(token, distinct_id)` - `apply-overflow-restrictions.ts`
- **Result types**: `ok`, `drop`, `redirect`
- **Note**: Split into two separate steps for cleaner separation of concerns
- **Status**: ✅ Implemented and tested
- **Files**: `steps/apply-drop-restrictions.ts`, `steps/apply-overflow-restrictions.ts`

### Step 3: Parse Kafka Message

- **Type**: Per-message, sequential
- **Input**: `{ message: Message, headers: EventHeaders }`
- **Output**: `{ message: Message, headers: EventHeaders, parsedMessage: ParsedMessageData }`
- **Operations**:
    - Call `kafkaParser.parseMessage(message)` which:
        - Checks if gzipped and decompresses
        - Parses JSON payload
        - Validates against schemas (`RawEventMessageSchema`, `EventSchema`, `SnapshotEventSchema`)
        - Extracts snapshot items and validates timestamps
    - **Redirect to DLQ if parse fails**
- **Result types**: `ok`, `dlq`
- **Note**: Uses existing `KafkaMessageParser.parseMessage()` method, made public for pipeline use
- **Status**: ✅ Implemented and tested
- **File**: `steps/parse-kafka-message.ts`

### Step 4: Resolve Team

- **Type**: Per-message, sequential
- **Input**: `{ message: Message, headers: EventHeaders, parsedMessage: ParsedMessageData }`
- **Output**: `MessageWithTeam`
- **Operations**:
    - Extract token from headers
    - Call `teamService.getTeamByToken(token)`
    - Validate team exists and is enabled
    - Get retention period via `teamService.getRetentionPeriodByTeamId()`
    - Drop if team missing or no retention period
- **Result types**: `ok`, `drop`
- **File**: `steps/resolve-team.ts`

### Step 5: Obtain Batch

- **Type**: Batch-level operation
- **Input**: `MessageWithTeam[]`
- **Output**: `MessageWithTeam & { batchRecorder: SessionBatchRecorder }[]`
- **Operations**:
    - Call `sessionBatchManager.getCurrentBatch()` once for entire batch
    - Attach batch recorder to each message
- **Note**: Requires `.gather()` before this step to collect all messages
- **File**: `steps/obtain-batch.ts`

### Step 6: Track Lib Version

- **Type**: Per-message, sequential (team-aware)
- **Input**: `MessageWithTeam & { batchRecorder: SessionBatchRecorder }`
- **Output**: `MessageWithTeam & { batchRecorder: SessionBatchRecorder }`
- **Operations**:
    - Call `libVersionMonitor.processSingle(input)`
    - Add warnings to context for `handleIngestionWarnings`
- **Note**: Requires **team-aware pipeline** to handle warnings
- **File**: `steps/track-lib-version.ts`

### Step 7: Record Session Event

- **Type**: Per-message, sequential (team-aware)
- **Input**: `MessageWithTeam & { batchRecorder: SessionBatchRecorder }`
- **Output**: `void`
- **Operations**:
    - Reset sessions revoked metric
    - Log debug info if enabled
    - Observe session info metrics
    - Call `batchRecorder.record(message)`
- **File**: `steps/record-session-event.ts`

### Step 8: Flush Batch

- **Type**: Batch-level operation
- **Input**: `void[]`
- **Output**: `void[]`
- **Operations**:
    - Check if `sessionBatchManager.shouldFlush()`
    - If true, call `sessionBatchManager.flush()`
- **Note**: Requires `.gather()` before this step to collect all processed messages
- **File**: `steps/flush-batch.ts`

---

## Pipeline Architecture

```typescript
private initializePipeline(): void {
    const pipelineConfig: PipelineConfig = {
        kafkaProducer: this.kafkaOverflowProducer!,
        dlqTopic: '', // Session recordings don't use DLQ currently
        promiseScheduler: this.promiseScheduler,
    }

    this.pipeline = newBatchPipelineBuilder<{ message: Message }, { message: Message }>()
        // Step 0: Collect batch metrics (batch-level)
        .pipeBatch(createCollectBatchMetricsStep())

        .messageAware((builder) =>
            builder
                // Steps 1-4: Parse and validate, sequential processing
                .sequentially((b) =>
                    b
                        // Step 1: Collect per-message metrics
                        .pipe(createCollectMetricsStep())

                        // Step 2: Apply restrictions (may drop/redirect to overflow)
                        .pipe(createApplyRestrictionsStep(
                            this.eventIngestionRestrictionManager,
                            this.overflowTopic,
                            this.consumeOverflow
                        ))

                        // Step 3: Parse message (redirect to DLQ on failure)
                        .pipe(createParseSessionRecordingMessageStep(
                            this.kafkaParser,
                            '' // DLQ topic if needed
                        ))

                        // Step 4: Resolve team and retention
                        .pipe(createResolveTeamStep(this.teamService))
                )
        )
        // Handle drops/redirects/DLQ from steps 1-4
        .handleResults(pipelineConfig)
        .handleSideEffects(this.promiseScheduler, { await: false })
        .gather()
        .filterOk()

        // Add team to context for team-aware pipeline
        .map((element) => ({
            result: element.result,
            context: {
                ...element.context,
                team: element.result.value.team,
            },
        }))

        // Steps 5-7: Team-aware processing with ingestion warnings
        .messageAware((builder) =>
            builder
                .teamAware((b) =>
                    b
                        // Gather all messages for batch operation
                        .gather()

                        // Step 5: Obtain batch recorder (batch-level)
                        .pipeBatch(createObtainBatchStep(this.sessionBatchManager))

                        // Steps 6-7: Process each message sequentially
                        .sequentially((seq) =>
                            seq
                                // Step 6: Track lib versions (adds warnings to context)
                                .pipe(createTrackLibVersionStep(this.libVersionMonitor))

                                // Step 7: Record to batch using batch recorder
                                .pipe(createRecordSessionEventStep(this.isDebugLoggingEnabled))
                        )
                )
                // Handle ingestion warnings from lib version monitor
                .handleIngestionWarnings(this.kafkaProducer!)
        )
        .handleResults(pipelineConfig)
        .handleSideEffects(this.promiseScheduler, { await: false })

        // Gather all processed messages before flushing
        .gather()

        // Step 8: Flush batch if needed (batch-level)
        .pipeBatch(createFlushBatchStep(this.sessionBatchManager))

        .build()
}
```

---

## Updated handleEachBatch

```typescript
public async handleEachBatch(messages: Message[]): Promise<void> {
    this.kafkaConsumer.heartbeat()

    if (messages.length > 0) {
        logger.info('🔁', `blob_ingester_consumer_v2 - handling batch`, {
            size: messages.length,
            partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
            assignedPartitions: this.assignedPartitions,
        })
    }

    await instrumentFn(
        { key: `recordingingesterv2.handleEachBatch`, sendException: false },
        async () => {
            // Create batch and feed to pipeline
            const batch = createBatch(messages.map((message) => ({ message })))
            this.pipeline.feed(batch)

            // Pipeline handles everything including metrics and flush
            await this.pipeline.next()

            // Heartbeat
            this.kafkaConsumer.heartbeat()
        }
    )
}
```

---

## Pipeline Steps Summary

| Step # | Name                      | Type        | When                    | Purpose                                   |
| ------ | ------------------------- | ----------- | ----------------------- | ----------------------------------------- |
| 0      | Collect Batch Metrics     | Batch-level | First step              | Track batch size/KB                       |
| 1      | Collect Metrics           | Per-message | Sequential              | Track message received metrics            |
| 2      | Apply Restrictions        | Per-message | Sequential              | Drop/redirect based on rules              |
| 3      | Parse Message             | Per-message | Sequential              | Decompress, parse, validate → DLQ on fail |
| 4      | Resolve Team              | Per-message | Sequential              | Look up team, check retention             |
| -      | Handle Results            | Pipeline    | After step 4            | Handle drops/redirects/DLQ                |
| -      | Gather                    | Pipeline    | After step 4            | Collect all results for team context      |
| -      | Gather                    | Pipeline    | Team-aware              | Collect messages for batch operation      |
| 5      | Obtain Batch              | Batch-level | Team-aware              | Get batch recorder from manager           |
| 6      | Track Lib Version         | Per-message | Sequential (team-aware) | Monitor versions, add warnings            |
| 7      | Record Session Event      | Per-message | Sequential (team-aware) | Add to batch using batch recorder         |
| -      | Handle Ingestion Warnings | Pipeline    | After step 7            | Emit warnings to Kafka                    |
| -      | Handle Results            | Pipeline    | After step 7            | Handle any errors                         |
| -      | Gather                    | Pipeline    | After step 7            | Collect all processed messages            |
| 8      | Flush Batch               | Batch-level | After gather            | Write to S3 if shouldFlush()              |

---

## Implementation Steps

### Phase 1: Create Pipeline Steps

Create these new step files in `steps/` directory:

0. `collect-batch-metrics.ts` - Step 0
1. `collect-metrics.ts` - Step 1
2. `apply-restrictions.ts` - Step 2
3. `parse-session-recording-message.ts` - Step 3
4. `resolve-team.ts` - Step 4
5. `obtain-batch.ts` - Step 5
6. `track-lib-version.ts` - Step 6
7. `record-session-event.ts` - Step 7
8. `flush-batch.ts` - Step 8

### Phase 2: Create Types

Create or update type definitions for pipeline inputs/outputs.

### Phase 3: Refactor Supporting Classes

1. **`LibVersionMonitor`**
    - Add `processSingle(message)` method that returns warnings
    - Keep `processBatch()` for backward compatibility

2. **`SessionRecordingRestrictionHandler`**
    - Logic moves into step 2
    - Can be removed or simplified

### Phase 4: Update Consumer Class

1. Add pipeline field to class
2. Implement `initializePipeline()` method
3. Update `handleEachBatch()` to use pipeline
4. Remove old methods:
    - `processBatchMessages()`
    - `processMessages()`
    - `consume()`

### Phase 5: Testing

1. Unit tests for each step
2. Integration tests for full pipeline
3. Regression tests to ensure existing behavior preserved
