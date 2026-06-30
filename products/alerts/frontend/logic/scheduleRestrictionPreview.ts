import type { BlockedWindow } from 'lib/components/Alerts/types'
import { dayjs } from 'lib/dayjs'

type ParsedWindow = { start: number; end: number; overnight: boolean }

function parseHHMM(value: string): number {
    const s = value.trim()
    const parts = s.split(':')
    if (parts.length !== 2) {
        throw new Error('invalid_hhmm')
    }
    const h = parseInt(parts[0], 10)
    const m = parseInt(parts[1], 10)
    if (Number.isNaN(h) || Number.isNaN(m) || h < 0 || h > 23 || m < 0 || m > 59) {
        throw new Error('invalid_hhmm')
    }
    return h * 60 + m
}

function parseWindowPair(start: string, end: string): ParsedWindow {
    const sm = parseHHMM(start)
    const em = parseHHMM(end)
    if (sm === em) {
        throw new Error('equal_ends')
    }
    return { start: sm, end: em, overnight: sm > em }
}

export function parseBlockedWindowsForPreview(windows: BlockedWindow[]): ParsedWindow[] {
    return windows.map((w) => parseWindowPair(w.start, w.end))
}

export function isLocalMinuteBlocked(minute: number, windows: ParsedWindow[]): boolean {
    for (const w of windows) {
        if (!w.overnight) {
            if (w.start <= minute && minute < w.end) {
                return true
            }
        } else if (w.end === 0) {
            if (minute >= w.start) {
                return true
            }
        } else if (minute >= w.start || minute < w.end) {
            return true
        }
    }
    return false
}

/** Rough count of evaluation slots in the next 24h that are not blocked at slot start (team TZ). */
export function estimateCheckSlotsNext24h(
    blockedWindows: BlockedWindow[] | null | undefined,
    teamTimezone: string,
    cadenceMinutes: 15 | 60
): number {
    const totalSlots = (24 * 60) / cadenceMinutes
    if (!blockedWindows?.length) {
        return totalSlots
    }
    let parsed: ParsedWindow[]
    try {
        parsed = parseBlockedWindowsForPreview(blockedWindows)
    } catch {
        return totalSlots
    }
    const start =
        cadenceMinutes === 60 ? dayjs().tz(teamTimezone).startOf('hour') : dayjs().tz(teamTimezone).startOf('minute')
    let count = 0
    for (let i = 0; i < totalSlots; i++) {
        const t = start.add(i * cadenceMinutes, 'minute')
        const minute = t.hour() * 60 + t.minute()
        if (!isLocalMinuteBlocked(minute, parsed)) {
            count++
        }
    }
    return count
}
