import { eventWithTime } from '@posthog/rrweb-types'

import { transformEventToWeb } from 'scenes/session-recordings/mobile-replay'

import { decompressEvent } from './decompress'

export type ErrorHandler = (error: unknown, phase: 'decompress' | 'transform') => void

export function toEventWithTime(d: unknown, onError?: ErrorHandler): eventWithTime {
    let currentEvent: unknown
    try {
        currentEvent = decompressEvent(d)
    } catch (e) {
        onError?.(e, 'decompress')
        currentEvent = d
    }

    try {
        return transformEventToWeb(currentEvent) ?? (currentEvent as eventWithTime)
    } catch (e) {
        onError?.(e, 'transform')
        return currentEvent as eventWithTime
    }
}
