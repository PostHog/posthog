# PostHog Ingestion Pipeline Overview

## Entry Point

The ingestion pipeline starts at `IngestionConsumer.handleKafkaBatch()` in `src/ingestion/ingestion-consumer.ts`. This method processes batches of Kafka messages containing analytics events.

## Data Flow Overview

```
Kafka Batch → Parse Messages → Event Normalization → Apply Ingestion Event Restrictions → Resolve Teams → Cookieless Processing → Group by Distinct ID → Hog Watcher → Concurrent Processing → Flush Stores
```

## Step-by-Step Breakdown

### 1. Parse Kafka Messages (`parseKafkaBatch`)

**Implementation:** [`src/ingestion/ingestion-consumer.ts:542-590`](src/ingestion/ingestion-consumer.ts#L542-L590)

**Input:** Raw Kafka `Message[]` objects
**Output:** `IncomingEvent[]` with parsed event data

**Required Data:** Raw Kafka message with JSON payload containing event data

**What it does:**
- Extracts `distinct_id` and `token` from message headers for early filtering
- Parses JSON payload into `PipelineEvent` objects

**Key data transformations:**
- Raw Kafka message → `PipelineEvent` with basic properties

### 2. Event Normalization

**Implementation:** [`src/utils/event.ts:203-241`](src/utils/event.ts#L203-L241)

**Input:** `IncomingEvent[]` with parsed event data
**Output:** `IncomingEvent[]` with normalized events

**Required Data:** `PipelineEvent` with basic properties (distinct_id, token, properties, ip, sent_at, etc.)

**What it does:**
- Applies event normalization via `normalizeEvent()`

**Key data transformations:**
- **String sanitization:** `distinct_id` and `token` converted to strings and sanitized
- **Property merging:** Top-level `$set` and `$set_once` merged into `properties.$set` and `properties.$set_once`
- **IP address handling:** `event.ip` moved to `properties.$ip` if not already present, then `event.ip` set to `null`
- **Person properties:** For non-snapshot/non-performance events, adds person and UTM properties via `personInitialAndUTMProperties()`
- **Timestamp handling:** `sent_at` moved to `properties.$sent_at`

**Person properties added:**
- **Mobile properties:** `$app_build`, `$app_name`, `$app_namespace`, `$app_version`
- **Web properties:** `$browser`, `$browser_version`, `$device_type`, `$current_url`, `$pathname`, `$os`, `$os_version`, `$referring_domain`, `$referrer`, `$screen_height`, `$screen_width`, `$viewport_height`, `$viewport_width`, `$raw_user_agent`
- **Campaign properties:** `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `gclid`, `gad_source`, `gclsrc`, `dclid`, `gbraid`, `wbraid`, `fbclid`, `msclkid`, `twclid`, `li_fat_id`, `mc_cid`, `igshid`, `ttclid`, `rdt_cid`, `epik`, `qclid`, `sccid`, `irclid`, `_kx`
- **Initial properties:** All person properties also added as `$initial_*` properties in `$set_once`
- **OS name fallback:** `$os_name` treated as fallback for `$os` when `$os` is not present

**Note:** Timestamp and offset processing does not happen during this initial normalization step. It occurs later in the concurrent processing phase (steps 9.4, 9.7, and 9.9).

### 3. Apply Ingestion Event Restrictions

**Implementation:** [`src/ingestion/ingestion-consumer.ts:542-590`](src/ingestion/ingestion-consumer.ts#L542-L590) (within `parseKafkaBatch`) and [`src/utils/event-ingestion-restriction-manager.ts`](src/utils/event-ingestion-restriction-manager.ts)

**Input:** `IncomingEvent[]` with normalized events
**Output:** `IncomingEvent[]` with filtered events

**Required Data:** Only `token` and `distinct_id` are needed for restriction decisions

**What it does:**
- Checks static configuration lists for tokens/distinct_ids to drop, skip person processing, or force overflow
- Uses async `EventIngestionRestrictionManager` with `BackgroundRefresher` to check dynamic Redis-based restrictions:
  - **Background caching:** Uses [`BackgroundRefresher`](src/utils/background-refresher.ts) to cache Redis configs with 60-second TTL
  - **Async refresh:** Triggers background refresh when cache expires, doesn't block processing
  - **Redis lookup:** Fetches from Redis keys `event_ingestion_restriction_dynamic_config:{restriction_type}`
  - **Fallback handling:** Returns empty config on Redis errors, continues processing
- Applies restrictions:
  - **Drop Event:** Completely removes events from processing
  - **Skip Person Processing:** Adds `$process_person_profile: false` flag
  - **Force Overflow:** Redirects events to overflow topic
- Logs dropped events and increments metrics

### 4. Resolve Teams (`resolveTeams`)

**Implementation:** [`src/ingestion/ingestion-consumer.ts:592-602`](src/ingestion/ingestion-consumer.ts#L592-L602)

**Input:** `IncomingEvent[]`
**Output:** `IncomingEventWithTeam[]` with resolved team data

**Required Data:** `token` or `team_id` from events, team database lookup

**What it does:**
- Calls `populateTeamDataStep()` for each event
- Resolves team information from tokens
- Filters out events with invalid/unresolved teams

**Key data:**
- Team ID, team settings, timezone
- Team-level configurations (cookieless mode, etc.)

### 5. Cookieless Processing (`cookielessManager.doBatch`)

**Implementation:** [`src/ingestion/cookieless/cookieless-manager.ts:250-593`](src/ingestion/cookieless/cookieless-manager.ts#L250-L593)

**Input:** `IncomingEventWithTeam[]`
**Output:** `IncomingEventWithTeam[]` with cookieless distinct_ids resolved

**Required Data:** Events with `$cookieless_mode: true`, team cookieless settings, Redis for salts/sessions

**What it does:**
- Processes events with `$cookieless_mode: true` property
- Generates hash-based distinct_ids for GDPR-compliant tracking
- Handles both stateless and stateful cookieless modes
- Manages session IDs and device IDs for cookieless users
- Drops unsupported events (`$create_alias`, `$merge_dangerously`)

**Key transformations:**
- `distinct_id: "__cookieless__"` → hash-based distinct_id
- Adds `$device_id` and `$session_id` properties
- Manages identify event collisions via Redis state

**Input Data for Distinct ID Computation:**
The cookieless distinct ID is computed from these event properties and data:

**Required Event Properties:**
- `$raw_user_agent` - User agent string for browser fingerprinting
- `$ip` - IP address for location-based identification
- `$host` - Host/domain for site identification
- `$timezone` (optional) - User's timezone for date calculations
- `$cookieless_extra` (optional) - Additional hash content for custom identification

**Required Event Data:**
- `timestamp` / `sent_at` / `now` - Event timestamp for date-based salt generation
- `team.id` - Team ID for salt isolation
- `team.timezone` - Team timezone for date calculations
- `team.cookieless_server_hash_mode` - Stateless vs stateful mode

**Hash Computation:**
The distinct ID hash combines:
- Daily salt (generated per team per day)
- Team ID
- IP address
- Root domain (extracted from host)
- User agent string
- Optional hash extra content
- Collision counter (for hash collisions)

**Output Properties:**
- `$distinct_id` - Hash-based cookieless identifier
- `$device_id` - Device identifier derived from base hash
- `$session_id` - Session identifier (UUID7) for session tracking

### 6. Group Events by Distinct ID (`groupEventsByDistinctId`)

**Implementation:** [`src/ingestion/ingestion-consumer.ts:604-622`](src/ingestion/ingestion-consumer.ts#L604-L622)

**Input:** `IncomingEventWithTeam[]`
**Output:** `IncomingEventsByDistinctId` grouped by `token:distinct_id`

**Required Data:** `token` and `distinct_id` from events for grouping

**What it does:**
- Groups events by `token:distinct_id` combination
- Maintains event ordering within each distinct_id group
- Enables parallel processing while preserving per-user event order

**Key data structure:**
```typescript
{
  "token:distinct_id": {
    token: string,
    distinctId: string,
    events: IncomingEventWithTeam[]
  }
}
```

### 7. Hog Watcher (Conditional)

**Implementation:** [`src/ingestion/ingestion-consumer.ts:624-642`](src/ingestion/ingestion-consumer.ts#L624-L642)

**Input:** Grouped events
**Output:** Cached hog function states

**Required Data:** Team IDs from grouped events, hog function database lookup

**What it does:**
- Samples events based on `CDP_HOG_WATCHER_SAMPLE_RATE`
- Fetches and caches hog function states for all teams in batch
- Prepares for CDP transformations

**Key data:**
- Hog function IDs for transformation steps
- Cached function states for performance

### 8. Concurrent Processing

**Implementation:** [`src/ingestion/ingestion-consumer.ts:644-680`](src/ingestion/ingestion-consumer.ts#L644-L680)

**Input:** Grouped events by distinct_id
**Output:** Processed events with person/group updates

**Required Data:** Events grouped by distinct_id, rate limiter state, overflow configuration

**What it does:**
- Processes each distinct_id group in parallel
- Applies overflow detection and redirection
- Runs individual event pipeline for each event

#### 8.1 Overflow Detection (`redirectEvents`)

**Implementation:** [`src/ingestion/ingestion-consumer.ts:682-730`](src/ingestion/ingestion-consumer.ts#L682-L730)

**Required Data:** `token:distinct_id` for rate limiting, overflow topic configuration

**What it does:**
- Checks rate limiting per `token:distinct_id`
- Forces overflow for configured token/distinct_id combinations
- Redirects events to overflow topic if capacity exceeded
- Preserves partition locality for forced overflow events

#### 8.2 Event Pipeline (`processEventsForDistinctId`)

**Implementation:** [`src/ingestion/ingestion-consumer.ts:732-740`](src/ingestion/ingestion-consumer.ts#L732-L740)

**Required Data:** Individual events with team data, person/group stores

**What it does:**
- Processes events sequentially within each distinct_id group
- Tracks `$set` usage in non-person events
- Runs `EventPipelineRunner` for each event

### 9. Event Pipeline Steps

**Implementation:** [`src/worker/ingestion/event-pipeline/runner.ts:185-384`](src/worker/ingestion/event-pipeline/runner.ts#L185-L384)

Each event goes through these steps in `EventPipelineRunner.runEventPipelineSteps()`:

#### 9.1 Validation (`validateEvent`)
**Implementation:** [`src/worker/ingestion/event-pipeline/runner.ts:93-119`](src/worker/ingestion/event-pipeline/runner.ts#L93-L119)
**Required Data:** Event properties and structure for validation
- Validates event properties and structure
- Captures ingestion warnings for invalid events

#### 9.2 Person Processing Flag (`$process_person_profile`)
**Implementation:** [`src/utils/event.ts:168-202`](src/utils/event.ts#L168-L202)
**Required Data:** Event properties with `$process_person_profile` flag
- Checks if person processing should be disabled
- Normalizes person-related properties

#### 9.3 Special Event Handling
**Implementation:** [`src/worker/ingestion/event-pipeline/runner.ts:250-270`](src/worker/ingestion/event-pipeline/runner.ts#L250-L270)
**Required Data:** Event type and properties for special handling
- `$$client_ingestion_warning`: Captures client warnings
- `$$heatmap`: Routes to heatmap pipeline

#### 9.4 Drop Old Events (`dropOldEventsStep`)
**Implementation:** [`src/worker/ingestion/event-pipeline/dropOldEventsStep.ts`](src/worker/ingestion/event-pipeline/dropOldEventsStep.ts)
**Required Data:** Event timestamp, retention period configuration
- Filters events older than configured retention period
- Uses `parseEventTimestamp()` to check event age against retention policies

#### 9.5 Plugin Processing (`pluginsProcessEventStep`)
**Implementation:** [`src/worker/ingestion/event-pipeline/pluginsProcessEventStep.ts`](src/worker/ingestion/event-pipeline/pluginsProcessEventStep.ts)
**Required Data:** Event data, enabled plugins configuration
- Runs enabled plugins on the event
- Plugins can modify or drop events

#### 9.6 CDP Transformation (`transformEventStep`)
**Implementation:** [`src/worker/ingestion/event-pipeline/transformEventStep.ts`](src/worker/ingestion/event-pipeline/transformEventStep.ts)
**Required Data:** Event data, hog function states, team configuration
- Applies hog function transformations
- Handles CDP (Customer Data Platform) logic

#### 9.7 Event Normalization (`normalizeEventStep`)
**Implementation:** [`src/worker/ingestion/event-pipeline/normalizeEventStep.ts`](src/worker/ingestion/event-pipeline/normalizeEventStep.ts)
**Required Data:** Event properties, timestamp data
- Normalizes event properties and structure
- Calls `parseEventTimestamp()` for clock skew adjustment and offset processing
- **JavaScript Implementation** ([`src/worker/ingestion/timestamps.ts:67-113`](src/worker/ingestion/timestamps.ts#L67-L113)):
  - **Clock skew adjustment:** Uses `sent_at` vs `now` to calculate client-server clock skew
  - **Offset application:** Applies `offset` (milliseconds) to adjust timestamps: `now.minus(Duration.fromMillis(offset))`
  - **Future event handling:** Caps events more than 23 hours in the future to current time
  - **Validation:** Ensures timestamps are valid and within reasonable bounds

#### 9.8 Person Processing (`processPersonsStep`)
**Implementation:** [`src/worker/ingestion/event-pipeline/processPersonsStep.ts`](src/worker/ingestion/event-pipeline/processPersonsStep.ts)
**Required Data:** Event data, person store, team settings
- Updates person properties and profiles
- Handles person merges and aliases
- Generates person-related Kafka messages

#### 9.9 Event Preparation (`prepareEventStep`)
**Implementation:** [`src/worker/ingestion/event-pipeline/prepareEventStep.ts`](src/worker/ingestion/event-pipeline/prepareEventStep.ts)
**Required Data:** Event data, team settings, AI event configuration
- Prepares event for ClickHouse ingestion
- Handles AI event processing (`$ai_generation`, `$ai_embedding`)
- Calls `parseEventTimestamp()` again for final timestamp validation
- Processes timestamps and warnings

#### 9.10 Heatmap Data Extraction (`extractHeatmapDataStep`)
**Implementation:** [`src/worker/ingestion/event-pipeline/extractHeatmapDataStep.ts`](src/worker/ingestion/event-pipeline/extractHeatmapDataStep.ts)
**Required Data:** Event properties containing heatmap data
- Extracts heatmap data from events
- Generates separate heatmap events

#### 9.11 Event Creation (`createEventStep`)
**Implementation:** [`src/worker/ingestion/event-pipeline/createEventStep.ts`](src/worker/ingestion/event-pipeline/createEventStep.ts)
**Required Data:** Event data, person data, team settings
- Creates final event for ClickHouse
- Handles person associations

#### 9.12 Event Emission (`emitEventStep` or `produceExceptionSymbolificationEventStep`)
**Implementation:** [`src/worker/ingestion/event-pipeline/emitEventStep.ts`](src/worker/ingestion/event-pipeline/emitEventStep.ts) / [`src/worker/ingestion/event-pipeline/produceExceptionSymbolificationEventStep.ts`](src/worker/ingestion/event-pipeline/produceExceptionSymbolificationEventStep.ts)
**Required Data:** Final event data, ClickHouse configuration, exception processing settings
- Sends event to ClickHouse or exception processing
- Generates Kafka acknowledgments

### 10. Store Flushing

**Implementation:** [`src/ingestion/ingestion-consumer.ts:299-305`](src/ingestion/ingestion-consumer.ts#L299-L305)

**Required Data:** Person store updates, group store updates, Kafka producer

**What it does:**
- Flushes person store updates to Kafka
- Flushes group store updates
- Reports batch metrics

## New Ingestion Pipeline Sequence

The current pipeline processes steps in this order:

**Event Pre-processing (sequential):**
1. **Parse Messages** - Parse JSON payload into PipelineEvent objects
2. **Event Normalization** - Normalize event properties and structure
3. **Apply Restrictions** - Check static/dynamic restrictions and filter events
4. **Resolve Teams** - Resolve team information from tokens
5. **Cookieless Processing** - Generate hash-based distinct_ids for cookieless events
6. **Group by Distinct ID** - Group events by token:distinct_id for parallel processing

**Concurrent Processing:**
7. **Overflow Detection** - Check rate limits and redirect to overflow if needed
8. **Event Processing** - Process events through the full pipeline

**Proposed new sequence:**

**Event Pre-processing (sequential):**
1. **Resolve Teams** - Resolve team information from tokens
2. **Apply Restrictions** - Check static/dynamic restrictions and filter events
3. **Drop Old Events** - Filter events older than retention period (requires timestamp in headers)
4. **Overflow Detection** - Check rate limits and redirect to overflow if needed
5. **Cookieless Processing** - Generate hash-based distinct_ids for cookieless events
6. **Group by Distinct ID** - Group events by token:distinct_id for parallel processing

**Concurrent Processing:**
7. **Parse Messages** - Parse JSON payload into PipelineEvent objects
8. **Event Normalization** - Normalize event properties and structure
9. **Event Processing** - Process events through the full pipeline

### Key Changes Required:

#### 1. Extract Cookieless Data to Kafka Headers
Currently, cookieless processing requires parsing the full event payload to access:
- `$raw_user_agent`
- `$ip`
- `$host`
- `$timezone`
- `$cookieless_extra`
- `timestamp` / `sent_at` / `now`

**Solution:** Extract these properties to Kafka headers during capture to avoid early parsing:
- `cookieless_user_agent`
- `cookieless_ip`
- `cookieless_host`
- `cookieless_timezone`
- `cookieless_extra`
- `cookieless_timestamp`

#### 2. Additional Header Extractions Needed
Other properties currently parsed from message payload that need header extraction:
- `token` (already exists)
- `distinct_id` (already exists)
- `$cookieless_mode` flag
- `event` name (for early filtering)
- `uuid` (for tracking)
- `timestamp` / `sent_at` / `now` (for drop old events step)

#### 3. Implementation Considerations
- **Capture changes:** Update capture endpoints to extract cookieless properties to headers
- **Rust capture:** Update `rust/capture/src/sinks/kafka.rs` to include cookieless headers
- **Ingestion consumer:** Modify `parseKafkaBatch` to work with headers-only data for early steps
- **Fallback handling:** Maintain ability to parse full payload if headers are missing
- **Backward compatibility:** Support both header-based and payload-based processing during transition

## Implementation Steps

**Required Changes:**

1. **Move resolve teams step** - Move to step 1
2. **Move apply restrictions step** - Move to step 2
3. **Move overflow detection step** - Move to step 4
4. **Add timestamps to kafka headers** - Extract timestamp data to headers for early filtering
5. **Move drop old events step** - Move to step 3
6. **Add cookieless info to headers** - Extract cookieless properties to headers
7. **Move the cookieless step** - Move to step 5
8. **Move parse messages step** - Move to step 7
9. **Move event normalization step** - Move to step 8
10. **Refactor timestamp handling** - Add separate timestamp fields to step interfaces
    - Add `rawTimestamps` field with timestamps copied from event
    - Add `timestamps` field with normalized timestamps
    - Update step interfaces to carry timestamp data separately
    - Implement once timestamps are available in headers
    - Avoid parsing and normalizing timestamps multiple times in various steps
