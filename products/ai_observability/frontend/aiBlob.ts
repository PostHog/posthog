/** Frontend twin of the ingestion pointer module: the only place phaiblob:// URIs are interpreted. */
export interface AiBlobPointer {
    version: string
    algo: string
    hash: string
    mime: string | null
    size: number | null
}

const POINTER_SCHEME = 'phaiblob://'
const POINTER_RE = /^phaiblob:\/\/(v1)\/(sha256)\/([0-9a-f]{64})(?:\?(.*))?$/
// TODO: replace the whole URL rather than its data component, so a valid data URL can't be clobbered.
const DATA_URI_WRAPPED_POINTER = /^data:[\w.+-]+\/[\w.+-]+;base64,(phaiblob:\/\/.*)$/

export function parseAiBlobPointer(value: string): AiBlobPointer | null {
    const unwrapped = DATA_URI_WRAPPED_POINTER.exec(value)?.[1] ?? value
    if (!unwrapped.startsWith(POINTER_SCHEME)) {
        return null
    }
    const match = POINTER_RE.exec(unwrapped)
    if (!match) {
        return null
    }
    const params = new URLSearchParams(match[4] ?? '')
    const sizeRaw = params.get('size')
    return {
        version: match[1],
        algo: match[2],
        hash: match[3],
        mime: params.get('mime'),
        size: sizeRaw && /^\d+$/.test(sizeRaw) ? parseInt(sizeRaw, 10) : null,
    }
}

export function resolveAiBlobUrl(value: string, teamId: number | string | null): string {
    const pointer = parseAiBlobPointer(value)
    if (!pointer || teamId === null || teamId === undefined || teamId === '') {
        return value
    }
    return `/api/projects/${teamId}/ai_blob/${pointer.version}/${pointer.algo}/${pointer.hash}`
}

/**
 * Resolves a raw `data` field (base64 payload or, post-offload, a phaiblob:// pointer) to a
 * renderable src: the blob endpoint URL if it's a pointer, otherwise the `data:` URI it always was.
 */
export function resolveDataUri(rawData: string, mimeType: string, teamId: number | string | null): string {
    const resolved = resolveAiBlobUrl(rawData, teamId)
    return resolved !== rawData ? resolved : `data:${mimeType};base64,${rawData}`
}
