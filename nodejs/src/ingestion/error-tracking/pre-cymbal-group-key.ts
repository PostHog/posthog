import { createHash } from 'crypto'

import { PluginEvent } from '~/plugin-scaffold'

const PRE_CYMBAL_FRAME_FIELD_SEP = '\0'
const PRE_CYMBAL_FRAME_SEP = '\x1e'

function updatePreCymbalFrameHash(hash: ReturnType<typeof createHash>, frame: Record<string, unknown>): void {
    hash.update(String(frame.function ?? ''))
    hash.update(PRE_CYMBAL_FRAME_FIELD_SEP)
    hash.update(String(frame.filename ?? frame.abs_path ?? ''))
    hash.update(PRE_CYMBAL_FRAME_FIELD_SEP)
    hash.update(String(frame.lineno ?? frame.line ?? ''))
    hash.update(PRE_CYMBAL_FRAME_FIELD_SEP)
    hash.update(String(frame.colno ?? frame.column ?? ''))
    hash.update(PRE_CYMBAL_FRAME_FIELD_SEP)
}

/** Pre-Cymbal stack signature for per-issue rate limit buckets. */
export function preCymbalGroupKey(event: PluginEvent): string | null {
    const exc = event.properties?.$exception_list?.[0]
    if (!exc) {
        return null
    }

    const frames = exc.stacktrace?.frames
    if (!frames?.length) {
        const value = exc.value ?? ''
        if (!value) {
            return null
        }
        return createHash('sha1')
            .update(`${exc.type ?? ''}|${value}`)
            .digest('hex')
            .slice(0, 16)
    }

    const hash = createHash('sha1')
    hash.update(String(exc.type ?? ''))
    hash.update('|')
    for (const frame of frames) {
        updatePreCymbalFrameHash(hash, frame as Record<string, unknown>)
        hash.update(PRE_CYMBAL_FRAME_SEP)
    }
    return hash.digest('hex').slice(0, 16)
}
