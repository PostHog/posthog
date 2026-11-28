import {
    blockedAndAllowedMinuteIntervalsForQuietHours,
    MINUTES_PER_DAY,
} from 'products/alerts/frontend/logic/scheduleRestrictionValidation'
import type { BlockedWindow } from 'products/alerts/frontend/types'

export type TimelineSegment = { kind: 'blocked' | 'allowed'; from: number; to: number }

export function buildDayTimelineSegments(windows: BlockedWindow[]): TimelineSegment[] | null {
    const both = blockedAndAllowedMinuteIntervalsForQuietHours(windows)
    if (both === null) {
        return null
    }
    const { blocked: merged, allowed } = both
    return [
        ...merged.map(([from, to]) => ({ kind: 'blocked' as const, from, to })),
        ...allowed.map(([from, to]) => ({ kind: 'allowed' as const, from, to })),
    ].sort((a, b) => a.from - b.from || a.to - b.to)
}

export function formatMinuteLabel(m: number): string {
    if (m <= 0 || m >= MINUTES_PER_DAY) {
        return '12a'
    }
    const h = Math.floor(m / 60)
    const isPm = h >= 12
    const hour12 = h % 12 === 0 ? 12 : h % 12
    return `${hour12}${isPm ? 'p' : 'a'}`
}

/** Hour starts 12am … 11pm (24 columns under the bar). */
export const HOUR_START_MINUTES = Array.from({ length: 24 }, (_, h) => h * 60)

export function timelineAriaPieces(segments: TimelineSegment[]): string[] {
    return segments.map((s) => {
        const kind = s.kind === 'allowed' ? 'alert may run' : 'quiet hours'
        return `${formatMinuteLabel(s.from)}–${formatMinuteLabel(s.to)} ${kind}`
    })
}
