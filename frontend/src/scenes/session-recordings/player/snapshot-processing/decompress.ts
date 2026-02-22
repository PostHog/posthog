import { gunzipSync, strFromU8, strToU8 } from 'fflate'

import { IncrementalSource } from '@posthog/rrweb-types'
import { EventType } from '@posthog/rrweb-types'

interface CompressedEvent {
    cv: string
    type: number
    data: any
    timestamp: number
}

function isCompressedEvent(ev: unknown): ev is CompressedEvent {
    return typeof ev === 'object' && ev !== null && 'cv' in ev
}

function unzip(compressedStr: string | undefined): any {
    if (!compressedStr) {
        return undefined
    }
    return JSON.parse(strFromU8(gunzipSync(strToU8(compressedStr, true))))
}

export function decompressEvent(ev: unknown): unknown {
    if (isCompressedEvent(ev)) {
        if (ev.cv === '2024-10') {
            if (ev.type === EventType.FullSnapshot && typeof ev.data === 'string') {
                return {
                    ...ev,
                    data: unzip(ev.data),
                }
            } else if (
                ev.type === EventType.IncrementalSnapshot &&
                typeof ev.data === 'object' &&
                'source' in ev.data
            ) {
                if (ev.data.source === IncrementalSource.StyleSheetRule) {
                    return {
                        ...ev,
                        data: {
                            ...ev.data,
                            source: IncrementalSource.StyleSheetRule,
                            adds: unzip(ev.data.adds),
                            removes: unzip(ev.data.removes),
                        },
                    }
                } else if (ev.data.source === IncrementalSource.Mutation && 'texts' in ev.data) {
                    return {
                        ...ev,
                        data: {
                            ...ev.data,
                            source: IncrementalSource.Mutation,
                            adds: unzip(ev.data.adds),
                            removes: unzip(ev.data.removes),
                            texts: unzip(ev.data.texts),
                            attributes: unzip(ev.data.attributes),
                        },
                    }
                }
            }
        } else {
            throw new Error(`Unknown compressed event version: ${ev.cv}`)
        }
    }
    return ev
}
