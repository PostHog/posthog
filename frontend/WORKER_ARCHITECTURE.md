# Session Recording Worker Architecture

## Problem
`processAllSnapshots` is CPU-intensive but transferring large snapshot data to/from workers is expensive.

## Solution: Hybrid Zero-Copy Approach

### Data Flow

```
API Response (compressed binary)
    ↓ (transfer ArrayBuffer)
Worker: Decompress + Parse + Transform
    ↓ (transfer processed ArrayBuffer)
Main Thread: Meta patching + Final assembly
```

### Key Optimizations

#### 1. Use Transferable Objects
```typescript
// Fetch returns ArrayBuffer
const compressedData = await response.arrayBuffer()

// TRANSFER to worker (zero-copy!)
worker.postMessage({
    type: 'process-snapshot-chunk',
    data: compressedData,
    sourceKey: 'blob_v2::key'
}, [compressedData]) // Transfer list - neuters main thread copy
```

#### 2. Stream Processing
```typescript
// Process chunks as they arrive, don't wait for all data
for await (const chunk of fetchSnapshotChunks()) {
    worker.postMessage({ chunk }, [chunk.buffer])
}
```

#### 3. Keep Processed Data in Worker
```typescript
// Worker maintains internal cache of processed snapshots
worker.postMessage({ type: 'process', sourceKey: 'blob_v2::key', data })

// Main thread only requests specific ranges
worker.postMessage({
    type: 'get-snapshots',
    sourceKey: 'blob_v2::key',
    timeRange: [startMs, endMs]
})

// Worker sends minimal data back (only requested range)
```

### Worker Responsibilities

**IN WORKER (CPU-intensive):**
- ✅ Snappy decompression
- ✅ JSON parsing (`JSON.parse` is CPU-intensive)
- ✅ Mobile transformation (`transformEventToWeb`)
- ✅ Chrome extension stripping
- ✅ Duplicate detection (hashing)
- ✅ Mutation chunking
- ✅ Maintain internal snapshot cache by sourceKey

**ON MAIN THREAD (needs UI context):**
- ✅ Meta patching (needs `viewportForTimestamp` from events)
- ✅ Final sorting/merging across sources
- ✅ Interfacing with Kea logic

### API Design

```typescript
// Worker Messages
type WorkerMessage =
    | { type: 'process-chunk', sourceKey: string, data: ArrayBuffer }
    | { type: 'get-processed', sourceKey: string }
    | { type: 'get-range', sourceKey: string, startMs: number, endMs: number }
    | { type: 'clear-cache', sourceKey?: string }

type WorkerResponse =
    | { type: 'chunk-processed', sourceKey: string, snapshotCount: number }
    | { type: 'snapshots', sourceKey: string, snapshots: RecordingSnapshot[] }
    | { type: 'error', error: string }

// Manager API
class SnapshotProcessingWorkerManager {
    async processChunk(sourceKey: string, compressedData: ArrayBuffer): Promise<void> {
        // Transfer ownership to worker
        this.worker.postMessage({
            type: 'process-chunk',
            sourceKey,
            data: compressedData
        }, [compressedData])
    }

    async getProcessedSnapshots(sourceKey: string): Promise<RecordingSnapshot[]> {
        // Only transfer back when needed
        return this.sendMessage({ type: 'get-processed', sourceKey })
    }

    async getSnapshotsInRange(
        sourceKey: string,
        startMs: number,
        endMs: number
    ): Promise<RecordingSnapshot[]> {
        // Even more efficient - only get what you need
        return this.sendMessage({ type: 'get-range', sourceKey, startMs, endMs })
    }
}
```

### Implementation Strategy

#### Phase 1: Move decompression + parsing
```typescript
// Worker handles binary → JSON
parseEncodedSnapshots(arrayBuffer) // Already uses DecompressionWorker
```

#### Phase 2: Keep processed data in worker
```typescript
// Worker maintains Map<SourceKey, RecordingSnapshot[]>
// Main thread requests ranges as needed
```

#### Phase 3: Incremental streaming
```typescript
// Process and cache as data arrives
// Don't wait for complete recording
```

### Memory Benefits

**Before:**
- Main: Compressed data (MB)
- Main: Parsed snapshots (MB)
- Main: Processed snapshots (MB)
- **Total: 3x data size in main thread**

**After:**
- Main: Compressed data (transferred to worker, neutered)
- Worker: Parsed + processed snapshots (MB)
- Main: Only current viewport range (~100 snapshots)
- **Total: ~1.1x data size, most in worker**

### Performance Benefits

1. **Zero-copy transfer** via transferable ArrayBuffers
2. **Parallel processing** during download (process chunks as they arrive)
3. **Reduced main thread work** (no JSON parsing/transformation on main thread)
4. **Lower memory pressure** on main thread (worker keeps bulk data)
5. **Range-based retrieval** (only transfer needed snapshots)

### Compatibility

- ✅ Transferable objects: Supported everywhere
- ✅ ArrayBuffer transfer: Supported everywhere
- ⚠️ SharedArrayBuffer: Requires COOP/COEP headers (skip for now)

### Migration Path

1. Start with `parseEncodedSnapshots` in worker (already has decompression)
2. Add internal caching in worker
3. Add range-based retrieval
4. Update `processAllSnapshots` to work with range-based data
5. Add streaming/chunked processing
