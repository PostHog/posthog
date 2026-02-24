# Optimizing HogFunction/HogFlow Globals: Property Pruning + Lazy Loading

## Problem Statement

When a HogFunction or HogFlow invocation is created,
we store **all** event properties and **all** person properties in the invocation globals.
These globals are then persisted to Kafka (topic `cdp_cyclotron_*`) and/or Postgres (Cyclotron jobs table)
for every single invocation.

Most functions only reference a handful of properties
(e.g., `event.properties.$browser`, `person.properties.email`),
yet we store potentially hundreds of properties per invocation.
This wastes storage, network bandwidth, and serialization time.

## Current Architecture

### Data Flow

```
Event (Kafka: events_json)
  → CdpEventsConsumer._parseKafkaBatch()
    → convertToHogFunctionInvocationGlobals(clickHouseEvent, team, siteUrl)
       ↳ Parses ALL event.properties (JSON string → object)
       ↳ Parses ALL person_properties (JSON string → object)
       ↳ Returns HogFunctionInvocationGlobals with full properties

  → processBatch()
    → createHogFunctionInvocations()
       ↳ enrichGroups() — adds ALL group properties
       ↳ filterFunctionInstrumented() — runs filter bytecode against ALL properties
       ↳ hogInputsService.buildInputsWithGlobals() — templates inputs using ALL properties
       ↳ createInvocation(globalsWithInputs, hogFunction) — stores full globals in state

    → createHogFlowInvocations()
       ↳ createHogFlowInvocation() — stores event properties in state (person NOT stored)

  → cyclotronJobQueue.queueInvocations()
    → Kafka: serializeInvocation() → JSON.stringify(state including all properties)
    → Postgres: invocationToCyclotronJobInitial() → vmState = invocation.state
```

### Where Properties Are Stored

| Path | What's stored | Storage medium |
|------|--------------|----------------|
| `invocation.state.globals.event.properties` | ALL event properties | Kafka + Postgres |
| `invocation.state.globals.person.properties` | ALL person properties | Kafka + Postgres |
| `invocation.state.globals.groups.*.properties` | ALL group properties | Kafka + Postgres |
| `invocation.state.globals.inputs` | Computed inputs (from templates that read properties) | Kafka + Postgres |

For HogFlows, the state is lighter:
- `state.event` (includes ALL event properties)
- Person is loaded fresh from DB at each step (NOT stored in state)

### Where Properties Are Read

Properties are consumed in four places:

1. **Filter bytecode** (`hog-function-filtering.ts`):
   Runs compiled HogQL filter bytecode against `HogFunctionFilterGlobals`.
   The bytecode accesses specific properties via `GET_GLOBAL` opcodes.
   Filter definitions also have explicit `key` fields on `EventPropertyFilter` / `PersonPropertyFilter`.

2. **Input templates** (`hog-inputs.service.ts`):
   Input values contain bytecode (Hog) or Liquid templates that reference `event.properties.*`, `person.properties.*`.
   These are resolved via `formatHogInput()` or `formatLiquidInput()`.

3. **Main Hog bytecode** (the function's `hog` code):
   The compiled bytecode accesses globals via `GET_GLOBAL` opcodes with chains like
   `['event', 'properties', '$browser']`.

4. **Masking bytecode**: The masking hash configuration also has bytecode.

### Key Files

| File | Role |
|------|------|
| `nodejs/src/cdp/utils.ts:34` | `convertToHogFunctionInvocationGlobals()` — builds globals with ALL properties |
| `nodejs/src/cdp/types.ts:71` | `HogFunctionInvocationGlobals` type — defines the globals shape |
| `nodejs/src/cdp/services/hog-executor.service.ts:173` | `buildHogFunctionInvocations()` — filters + builds invocations |
| `nodejs/src/cdp/services/hog-inputs.service.ts:23` | `buildInputs()` — templates inputs using globals |
| `nodejs/src/cdp/utils/hog-function-filtering.ts:225` | `convertToHogFunctionFilterGlobal()` — builds filter globals |
| `nodejs/src/cdp/utils/invocation-utils.ts:11` | `createInvocation()` — wraps globals into invocation state |
| `nodejs/src/cdp/services/job-queue/job-queue-kafka.ts:120` | `queueInvocations()` — serializes to Kafka |
| `nodejs/src/cdp/services/job-queue/job-queue-postgres.ts:219` | `invocationToCyclotronJobInitial()` — stores as vmState |
| `nodejs/src/cdp/services/hogflows/hogflow-executor.service.ts:41` | `createHogFlowInvocation()` — stores event in flow state |
| `common/hogvm/typescript/src/execute.ts:468` | `GET_GLOBAL` opcode — how bytecode accesses globals |

## Proposed Approach: Static Property Extraction + Pruning

### Overview

When a HogFunction or HogFlow is saved (or its compiled bytecode changes),
statically analyze all bytecode and configuration to extract the set of required property keys.
Store this set on the function definition.
At invocation time, use this set to prune the globals before storing them.

### Phase 1: Property Extraction (at save/compile time)

#### 1a. Extract from filter definitions (easy, high confidence)

Filter definitions have explicit property references:

```typescript
// HogFunctionFilterEvent.properties contains typed filters:
{ type: 'event', key: '$browser', operator: 'exact', value: 'Chrome' }
{ type: 'person', key: 'email', operator: 'is_set' }
```

These directly tell us which `event.properties.*` and `person.properties.*` keys are needed.

Implementation: iterate `hogFunction.filters.events[].properties[]`
and `hogFunction.filters.properties[]` and collect all keys by type.

#### 1b. Extract from bytecode (medium difficulty, high confidence for static access)

The Hog VM's `GET_GLOBAL` opcode works as follows:
```
PUSH "event"
PUSH "properties"
PUSH "$browser"
GET_GLOBAL 3
```

This pushes 3 string constants then calls `GET_GLOBAL` with count=3,
producing a chain `['event', 'properties', '$browser']`.

**Static analysis approach**: scan the bytecode array looking for `GET_GLOBAL` opcodes,
then walk backward to find the preceding `STRING` pushes.
If the chain starts with `event.properties.*` or `person.properties.*`,
record the property key.

This covers:
- Filter bytecode (`hogFunction.filters.bytecode`)
- Input bytecode (values in `hogFunction.inputs.*.bytecode`)
- Main hog bytecode (`hogFunction.bytecode`)
- Masking bytecode (`hogFunction.masking.bytecode`)
- Mapping filter bytecodes (`hogFunction.mappings[].filters.bytecode`)

**Limitations**:
- Dynamic property access (e.g., `event.properties[dynamicVar]`) cannot be statically resolved.
  In this case we must fall back to keeping all properties of that type.
- If any bytecode uses `GET_GLOBAL 1` with just `['event']` or `['person']` at the top level,
  we must assume all properties of that object are needed.

#### 1c. Extract from Liquid templates (medium difficulty)

Liquid templates reference properties like `{{ event.properties.$browser }}`.
A regex/parser can extract these references.

#### 1d. Store the result

Add a computed field to the HogFunction/HogFlow model:

```typescript
type RequiredProperties = {
  event: string[] | '*'      // specific keys or '*' meaning all
  person: string[] | '*'     // specific keys or '*' meaning all
  groups: Record<number, string[] | '*'>  // per group type index
}
```

- `'*'` means "keep all properties" (used when dynamic access is detected
  or the function uses patterns like `jsonStringify(event.properties)`)
- An empty array means no properties of that type are needed

This should be computed on the backend (Python side) when the function is saved,
or on the Node.js side when compiling the function.
It should be stored on the `HogFunction` model as a JSON field.

### Phase 2: Property Pruning (at invocation time)

#### 2a. For HogFunctions

In `buildHogFunctionInvocations()` (hog-executor.service.ts),
after input building but before `createInvocation()`:

```typescript
function pruneGlobals(
  globals: HogFunctionInvocationGlobalsWithInputs,
  requiredProperties: RequiredProperties
): HogFunctionInvocationGlobalsWithInputs {
  return {
    ...globals,
    event: {
      ...globals.event,
      properties: requiredProperties.event === '*'
        ? globals.event.properties
        : pick(globals.event.properties, requiredProperties.event),
    },
    person: globals.person ? {
      ...globals.person,
      properties: requiredProperties.person === '*'
        ? globals.person.properties
        : pick(globals.person.properties, requiredProperties.person),
    } : undefined,
    // Similar for groups
  }
}
```

**Important**: Pruning must happen AFTER input building and AFTER filtering,
because both of those need the full properties to work correctly.
The pruned globals are only for what gets stored in the invocation state.

#### 2b. For HogFlows

In `createHogFlowInvocation()` (hogflow-executor.service.ts),
prune the event properties stored in `state.event`.
Person properties don't need pruning here since they're not stored in state.

However, HogFlows are more complex because the required properties
depend on ALL actions in the flow, not just one function.
The union of all action property requirements must be kept.

#### 2c. Filtering globals are separate

`HogFunctionFilterGlobals` is built fresh from the event data
and used only for filtering (not stored).
No changes needed here.

### Phase 3: Handling Edge Cases

#### Functions that need ALL properties

Some destination templates send the full event payload
(e.g., "send all event data to webhook").
These will have `required_properties.event = '*'`.
No pruning occurs — this is the current behavior, just explicit.

#### Dynamic property access patterns

If bytecode analysis encounters:
- `GET_GLOBAL 2` with chain `['event', 'properties']`
  (accessing the properties object itself, not a specific key)
- `CALL_GLOBAL` with `jsonStringify` or `keys` on `event.properties`
- Any pattern where the property key is not a literal string

Then mark that property category as `'*'`.

#### Backward compatibility

When `required_properties` is null/undefined (old functions not yet recompiled),
treat it as `{ event: '*', person: '*', groups: '*' }` — keep everything.
This ensures no behavior change for existing functions.

#### Template property requirements

Templates have their own bytecode.
When a function uses a template,
the template's property requirements must be merged with the function's own.

### Quantified Impact Estimate

For a typical destination that filters by `$current_url` contains "pricing"
and sends `event`, `distinct_id`, and `$browser` to a webhook:

- **Current**: stores 100+ event properties + 50+ person properties ≈ 5-20 KB per invocation
- **After**: stores 2 event properties + 0 person properties ≈ 0.2 KB per invocation
- **Reduction**: ~90-99% reduction in stored data per invocation

This compounds across millions of invocations per day.

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Static analysis misses a property reference | Default to `'*'` on any ambiguity; add a "force all properties" toggle |
| Breaking existing functions | Backward compat: null `required_properties` → keep all |
| Input templates using dynamic property keys | Detect and mark as `'*'` |
| Performance overhead of bytecode analysis | One-time cost at save/compile, amortized over millions of invocations |
| Functions that iterate over properties (`for key in event.properties`) | Detected by `GET_GLOBAL 2` pattern → mark as `'*'` |

## Step 1 Implementation Order

1. **Bytecode analyzer utility** — new module that scans bytecode for `GET_GLOBAL` patterns
   and extracts property chains. Includes Liquid template scanning.
2. **Property extraction at save time** — integrate analyzer into the HogFunction save flow
   (Python API or Node.js compilation step). Store `required_properties` on the model.
3. **Pruning at invocation time** — add `pruneGlobals()` call in the invocation creation path,
   guarded by a feature flag.
4. **Metrics** — add a metric comparing pre/post prune sizes to quantify savings.
5. **Gradual rollout** — enable via feature flag per team, then globally.
6. **HogFlow support** — extend to flows (union of all action requirements).

## Step 2: Lazy-Load Person and Group Properties (Don't Store Them)

### Motivation

Step 1 prunes properties to only what the function needs,
but we still store those properties in every invocation.
For person and group properties specifically,
we can go further: **don't store them at all** —
store only the person ID / distinct ID and group keys,
then load properties dynamically at execution time.

This is the pattern HogFlows already use for person data.
Extending it to HogFunctions (and to groups for both) would dramatically
reduce Warpstream/Kafka throughput since person/group properties
are often the largest part of the globals payload.

### Current State

| Path | HogFunctions | HogFlows |
|------|-------------|----------|
| Person properties | Stored in `globals.person.properties` | **Not stored** — loaded fresh via `PersonsManagerService` |
| Group properties | Stored in `globals.groups.*.properties` | Not enriched (TODO comment in code) |
| Event properties | Stored in `globals.event.properties` | Stored in `state.event.properties` |

HogFlows already load person data fresh at execution via:
```typescript
// cdp-cyclotron-worker-hogflow.consumer.ts
const dbPerson = await this.personsManager.get({
    teamId: hogFlow.team_id,
    distinctId: hogFlowInvocationState.event.distinct_id,
})
```

The `PersonsManagerService` uses `LazyLoader` with:
- **Batching**: multiple concurrent `.get()` calls batched into single DB query
- **Caching**: 1-minute refresh age (person data changes frequently)
- **Metrics**: cache hit rate, buffer usage, cache size

Similarly, `GroupsManagerService` already supports batch loading via
`fetchGroupProperties()` with 10-minute group type caching.

### Proposed Changes

#### 2a. Store only person ID + distinct_id in HogFunction globals

Instead of storing the full person object with all properties:

```typescript
// Before (current)
globals.person = {
    id: personUUID,
    properties: { email: '...', plan: '...', ...hundredsOfProps },
    name: 'User Name',
    url: '...',
}

// After
globals.person = {
    id: personUUID,
    distinct_id: event.distinct_id,  // needed for DB lookup
    name: 'User Name',  // pre-computed, cheap
    url: '...',          // pre-computed, cheap
    // properties omitted — loaded at execution time
}
```

At execution time in the Cyclotron worker,
before running the Hog VM, load person properties:

```typescript
// In cdp-cyclotron-worker.consumer.ts (or equivalent)
if (invocation.globals.person?.distinct_id) {
    const person = await this.personsManager.get({
        teamId: invocation.globals.project.id,
        distinctId: invocation.globals.person.distinct_id,
    })
    if (person) {
        invocation.globals.person.properties = person.properties
    }
}
```

This uses the existing `PersonsManagerService` with its batching and caching —
no new infrastructure needed.

#### 2b. Store only group keys in HogFunction globals

Similarly for groups:

```typescript
// Before (current)
globals.groups = {
    company: {
        id: 'acme-corp',
        index: 0,
        type: 'company',
        url: '...',
        properties: { name: '...', plan: '...', ...manyProps },
    }
}

// After
globals.groups = {
    company: {
        id: 'acme-corp',
        index: 0,
        type: 'company',
        url: '...',
        // properties omitted — loaded at execution time
    }
}
```

At execution time, use `GroupsManagerService.enrichGroups()` or a similar
method to batch-load group properties for the invocation.

#### 2c. Move enrichment from event consumer to worker

Currently `enrichGroups()` is called in the event consumer path
(`cdp-events.consumer.ts` line 91) during invocation creation.
This enrichment should move to the worker execution path:

```
Before:
  Event Consumer → enrichGroups() → store full globals → Kafka → Worker → execute

After:
  Event Consumer → store minimal globals → Kafka → Worker → load person + groups → execute
```

This shifts the DB load from the event consumer to the worker,
which is better because:
- Workers can scale independently
- Workers already do this for HogFlows
- The event consumer becomes faster (less DB work per event)
- Kafka/Warpstream payload sizes shrink dramatically

#### 2d. Input building must happen at execution time too

Currently, input templates are resolved in the event consumer
using full globals (including person/group properties).
If we defer property loading, input building must also be deferred.

For HogFunctions with `type: 'destination'`, inputs are pre-built.
This would need to change — inputs would be built at execution time
after properties are loaded.

**Alternative**: keep a hybrid approach where Step 1's pruned properties
are still stored for input building, but person/group properties
are loaded fresh. This avoids changing the input building flow.

#### 2e. Filtering still needs properties at event consumer time

The filtering step (`filterFunctionInstrumented()`) runs in the event consumer
and needs person/group properties to evaluate filters.
This **cannot** be deferred since filtering determines whether
an invocation is created at all.

Two approaches:
1. **Keep full properties for filtering, strip before storing**:
   Filter with full data, then remove person/group properties from globals
   before queuing to Kafka. Properties are loaded fresh at execution time.
2. **Accept the trade-off**: Person properties are already in the event payload
   (from ClickHouse event's `person_properties` field), so the event consumer
   has them for free. Groups require a DB lookup — this already happens.
   The win is not avoiding the initial load, but avoiding storing/transmitting the data.

Approach 1 is simpler and preserves the current filtering behavior exactly.

### Interaction with Step 1

Step 1 (static property extraction + pruning) and Step 2 (lazy loading)
are complementary:

- **Step 1 alone**: reduces properties from hundreds to a handful, stored in globals
- **Step 2 alone**: removes person/group properties entirely from stored globals, loads fresh
- **Step 1 + Step 2**: Step 1 still applies to **event** properties (which can't be lazy-loaded
  since events are immutable and from ClickHouse).
  Step 2 handles person/group properties (which are mutable and in Postgres).

For event properties, lazy loading is not practical because:
- Events live in ClickHouse, not Postgres (higher query latency)
- Ingestion lag means the event may not be queryable yet
- Event properties are immutable, so staleness isn't a concern — storing them is fine

### Impact Estimate

For a typical invocation with 100 event properties, 50 person properties, and 20 group properties:

| Component | Before | After Step 1 | After Step 1 + Step 2 |
|-----------|--------|-------------|----------------------|
| Event properties | ~10 KB | ~0.2 KB (pruned) | ~0.2 KB (pruned) |
| Person properties | ~5 KB | ~1 KB (pruned) | ~0.05 KB (ID only) |
| Group properties | ~3 KB | ~0.5 KB (pruned) | ~0.05 KB (key only) |
| **Total** | **~18 KB** | **~1.7 KB** | **~0.3 KB** |

Step 2 brings an additional ~5-6x reduction on top of Step 1,
for a combined ~60x reduction from baseline.
On millions of invocations per day, this translates to massive Warpstream bandwidth savings.

### Latency Trade-off

Loading person/group data at execution time adds latency:

| Operation | Estimated latency |
|-----------|------------------|
| Person lookup (cached in LazyLoader) | ~0 ms (cache hit) |
| Person lookup (cache miss, batched) | ~10-50 ms |
| Group properties lookup (batched) | ~10-50 ms |

This is acceptable because:
- `LazyLoader` batching amortizes cost across concurrent invocations
- 1-minute caching means most lookups are cache hits for active persons
- Workers already accept this latency for HogFlows
- The bandwidth savings far outweigh the added latency

### Freshness Consideration

Loading person/group properties at execution time instead of storage time
means the function sees **current** properties, not properties at trigger time.
This is generally better (more accurate), but could surprise users
if a person's properties changed between event capture and function execution.

For most destinations (webhooks, CRMs) this is actually preferred —
you want to send the current email, not the email from 5 minutes ago.

### Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| DB load increases on workers | LazyLoader batching + caching limits queries; read replicas available |
| Person deleted between trigger and execution | Graceful handling: if person not found, use empty properties |
| Input building needs properties | Hybrid approach: build inputs at execution time after loading properties |
| Increased execution latency | Batching amortizes; 10-50ms acceptable for async destinations |
| Group enrichment not yet enabled for HogFlows | This work would implement it properly for both paths |

### Implementation Order

1. **Refactor HogFunction worker to load person properties** —
   follow the HogFlow pattern using `PersonsManagerService`.
   Store only person ID + distinct_id in globals. Feature-flagged.
2. **Refactor HogFunction worker to load group properties** —
   use `GroupsManagerService` at execution time.
   Store only group keys in globals. Feature-flagged.
3. **Move input building to execution time** —
   defer input template resolution to after property loading.
   This is the largest change and requires careful testing.
4. **Remove `enrichGroups()` from event consumer** —
   once workers handle group loading, remove from the hot path.
5. **Metrics and monitoring** —
   track Kafka payload sizes, worker latency, cache hit rates.
6. **Gradual rollout** — per team, then globally.

## Alternative Approaches Considered

### Runtime Proxy-based tracking

Use JavaScript Proxies on the globals object during execution to track which properties
are actually accessed, then only persist those.

**Pros**: 100% accurate, no static analysis needed.
**Cons**: Runtime overhead per execution, still stores full globals initially
(pruning only on re-queue), adds complexity to the hot path.

### Lazy loading from ClickHouse event store (for event properties)

Instead of storing event properties in the invocation state,
store only the event UUID and load event properties from ClickHouse on demand.

**Pros**: Minimal storage for event data too.
**Cons**: Adds ClickHouse read latency to every invocation step,
ClickHouse may not have the event yet (ingestion lag),
significantly changes the architecture.

**Note**: This is different from Step 2's approach which lazy-loads
**person/group** properties from **Postgres** (low latency, already cached).
Event properties remain in ClickHouse where lazy loading is impractical.

### Compression only

Just compress the globals better (e.g., better gzip settings, zstd).

**Pros**: Simple, no behavior change.
**Cons**: Only reduces storage by 2-5x, not 10-100x.
Already partially implemented (`CDP_CYCLOTRON_COMPRESS_KAFKA_DATA`).

## Conclusion

The two-step approach provides compounding bandwidth savings:

**Step 1 — Static property pruning** (event + person + group properties):
- ~90% reduction in stored data for most functions
- One-time analysis at save time, amortized over millions of invocations
- Backward compatible with `'*'` fallback for dynamic access

**Step 2 — Lazy-load person/group properties** (don't store them at all):
- Additional ~5-6x reduction on top of Step 1
- Reuses existing infrastructure (`PersonsManagerService`, `GroupsManagerService`, `LazyLoader`)
- Follows the pattern HogFlows already use for person data
- Shifts DB load from event consumer to workers (which scale better)

Combined, these steps reduce a typical invocation payload from ~18 KB to ~0.3 KB —
a ~60x reduction that compounds across millions of daily invocations,
translating to massive Warpstream/Kafka bandwidth and storage savings.
