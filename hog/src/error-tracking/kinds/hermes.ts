import { readFileSync } from 'node:fs'

import { SymbolDataType, writeSymbolData } from '../container'
import { decodeUtf8 } from '../json'
import type { SymbolSetUpload } from '../upload'
import { isEmptyMapContent, loadMapContent, serializeMapContent, type MapContent } from './js'

// React Native with Hermes: Metro writes `.bundle` or `.jsbundle` files that get chunk IDs like
// JavaScript bundles. The Hermes compiler then composes a second map for the bytecode, and that
// composed map is what PostHog symbolicates with.

export const HERMES_BUNDLE_EXTENSIONS = ['.bundle', '.jsbundle'] as const

const FUNCTION_OFFSETS = 'x_hermes_function_offsets'

export function isHermesBundlePath(path: string): boolean {
    return HERMES_BUNDLE_EXTENSIONS.some((extension) => path.endsWith(extension))
}

// posthog-cli refuses to upload a map without this key, so it is what tells a composed map apart
// from Metro's packager map.
export function isComposedMap(path: string): boolean {
    try {
        return loadMapContent(decodeUtf8(readFileSync(path))).fields.has(FUNCTION_OFFSETS)
    } catch {
        return false
    }
}

export const uploadChunkId = (map: MapContent): string | null => map.chunkId ?? map.debugId

export function cloneMetadata(from: MapContent, to: MapContent): void {
    to.chunkId = uploadChunkId(from) ?? to.chunkId
    to.releaseId = from.releaseId
}

export type HermesMapSkip = 'no_chunk_id' | 'empty'

export function hermesSkipReason(map: MapContent): HermesMapSkip | undefined {
    if (uploadChunkId(map) === null) {
        return 'no_chunk_id'
    }
    return isEmptyMapContent(map) ? 'empty' : undefined
}

export function hermesUpload(map: MapContent): SymbolSetUpload {
    return {
        chunkId: uploadChunkId(map)!,
        releaseId: map.releaseId,
        data: writeSymbolData(SymbolDataType.HermesMap, Buffer.from(serializeMapContent(map), 'utf8')),
    }
}
