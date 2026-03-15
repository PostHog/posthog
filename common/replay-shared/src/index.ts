export type { ReplayTelemetry } from './telemetry'
export { noOpTelemetry } from './telemetry'

export type {
    EncodedRecordingSnapshot,
    RecordingSegment,
    RecordingSnapshot,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
} from './types'
export { SnapshotSourceType } from './types'

export { isObject, isEmptyObject } from './utils'

// snapshot processing
export { chunkMutationSnapshot, MUTATION_CHUNK_SIZE } from './snapshot-processing/chunk-large-mutations'
export {
    CHROME_EXTENSION_DENY_LIST,
    stripChromeExtensionDataFromNode,
    stripChromeExtensionData,
} from './snapshot-processing/chrome-extension-stripping'
export { decompressEvent } from './snapshot-processing/decompress'
export type { ViewportResolution } from './snapshot-processing/patch-meta-event'
export { extractDimensionsFromMobileSnapshot, getHrefFromSnapshot } from './snapshot-processing/patch-meta-event'
export type { SourceKey } from './snapshot-processing/source-key'
export { keyForSource } from './snapshot-processing/source-key'
export { throttleCapture, clearThrottle } from './snapshot-processing/throttle-capturing'
export type { RegisterWindowIdCallback, ProcessingCache } from './snapshot-processing/process-all-snapshots'
export {
    createWindowIdRegistry,
    processAllSnapshots,
    parseJsonSnapshots,
    hasAnyWireframes,
} from './snapshot-processing/process-all-snapshots'
export type { SnappyDecompressor } from './snapshot-processing/parse-encoded-snapshots'
export { parseEncodedSnapshots } from './snapshot-processing/parse-encoded-snapshots'

// mobile replay
export { transformEventToWeb, transformToWeb } from './mobile'
export { PLACEHOLDER_SVG_DATA_IMAGE_URL } from './mobile/transformer/shared'

// segmenter
export { createSegments, mergeInactiveSegments, mapSnapshotsToWindowId } from './segmenter'

// snapshot store
export { SnapshotStore } from './snapshot-store/SnapshotStore'
export type { SourceEntry, LoadBatch, SourceLoadingState, Mode } from './snapshot-store/types'

// canvas replay
export type { CanvasPluginErrorHandler } from './canvas/canvas-plugin'
export { CanvasReplayerPlugin } from './canvas/canvas-plugin'

// rrweb plugins and config
export {
    AudioMuteReplayerPlugin,
    CorsPlugin,
    COMMON_REPLAYER_CONFIG,
    HLSPlayerPlugin,
    WindowTitlePlugin,
} from './rrweb-plugins'
