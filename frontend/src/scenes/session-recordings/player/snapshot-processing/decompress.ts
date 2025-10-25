import { gunzipSync, strFromU8, strToU8 } from 'fflate'
import posthog from 'posthog-js'
import { compressedEventWithTime } from 'posthog-js/lib/src/extensions/replay/external/lazy-loaded-session-recorder'

import { IncrementalSource } from '@posthog/rrweb-types'
import { EventType } from '@posthog/rrweb-types'

import { throttleCapture } from './throttle-capturing'

function isCompressedEvent(ev: unknown): ev is compressedEventWithTime {
    return typeof ev === 'object' && ev !== null && 'cv' in ev
}

function unzip(compressedStr: string | undefined): any {
    if (!compressedStr) {
        return undefined
    }
    return JSON.parse(strFromU8(gunzipSync(strToU8(compressedStr, true))))
}

/**
 *
 * takes an event that might be from web, might be from mobile,
 * and might be partially compressed,
 * and decompresses it when possible
 *
 * you can't return a union of `KnownType | unknown`
 * so even though this returns `eventWithTime | unknown`
 * it has to be typed as only unknown
 *
 * KLUDGE: we shouldn't need so many type assertions on ev.data but TS is not smart enough to figure it out
 */
export function decompressEvent(ev: unknown, sessionRecordingId: string): unknown {
    try {
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
                throttleCapture(`${sessionRecordingId}-unknown-compressed-event-version`, () => {
                    posthog.captureException(new Error('Unknown compressed event version'), {
                        feature: 'session-recording-compressed-event-decompression',
                        compressedEvent: ev,
                        compressionVersion: ev.cv,
                    })
                })
                // probably unplayable but we don't know how to decompress it
                return ev
            }
        }
        return ev
    } catch (e) {
        throttleCapture(`${sessionRecordingId}-unknown-compressed-event-version`, () => {
            posthog.captureException((e as Error) || new Error('Could not decompress event'), {
                feature: 'session-recording-compressed-event-decompression',
                compressedEvent: ev,
            })
        })
        return ev
    }
}
