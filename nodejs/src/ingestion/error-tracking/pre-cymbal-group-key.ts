import { createHash } from 'crypto'

import { PluginEvent } from '~/plugin-scaffold'

const PRE_CYMBAL_FRAME_FIELD_SEP = '\0'
const PRE_CYMBAL_FRAME_SEP = '\x1e'
const PRE_CYMBAL_EXC_SEP = '\x1d'

function updatePreCymbalFrameHash(hash: ReturnType<typeof createHash>, frame: Record<string, unknown>): void {
    hash.update(String(frame.function ?? ''))
    hash.update(PRE_CYMBAL_FRAME_FIELD_SEP)
    hash.update(String(frame.filename ?? frame.abs_path ?? ''))
    hash.update(PRE_CYMBAL_FRAME_FIELD_SEP)
}

export function preCymbalGroupKey(event: PluginEvent): string | null {
    const excList = event.properties?.$exception_list
    if (!Array.isArray(excList) || excList.length === 0) {
        return null
    }

    const hash = createHash('sha1')
    let hasContent = false

    for (const exc of excList) {
        if (!exc || typeof exc !== 'object') {
            continue
        }
        const rawFrames = exc.stacktrace?.frames
        const frames = Array.isArray(rawFrames) ? rawFrames : null
        const value = exc.value ?? ''
        if (!frames?.length && !value) {
            continue
        }

        hasContent = true
        hash.update(String(exc.type ?? ''))
        hash.update(PRE_CYMBAL_FRAME_FIELD_SEP)

        // Mirror Cymbal grouping: in_app frames if any, else all frames, else the
        // raw message. Line/column are excluded — they shift across deploys for the
        // same issue and otherwise split it across rate-limit buckets.
        const safeFrames = frames?.map((frame) =>
            frame && typeof frame === 'object' ? (frame as Record<string, unknown>) : {}
        )
        const inAppFrames = safeFrames?.filter((frame) => frame.in_app === true)
        const usedFrames = inAppFrames?.length ? inAppFrames : safeFrames

        if (usedFrames?.length) {
            for (const frame of usedFrames) {
                updatePreCymbalFrameHash(hash, frame)
                hash.update(PRE_CYMBAL_FRAME_SEP)
            }
        } else {
            hash.update(String(value))
        }
        hash.update(PRE_CYMBAL_EXC_SEP)
    }

    if (!hasContent) {
        return null
    }
    return hash.digest('hex').slice(0, 16)
}
