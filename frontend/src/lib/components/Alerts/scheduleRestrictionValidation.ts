import type { BlockedWindow, ScheduleRestriction } from './types'

export const MAX_BLOCKED_WINDOWS = 5
export const MIN_BLOCKED_WINDOW_MINUTES = 30

export const MINUTES_PER_DAY = 1440

export type QuietHoursIssue = { kind: 'row'; index: number; message: string } | { kind: 'form'; message: string }

type ParsedSegment = { start: number; end: number; overnight: boolean }

/** Strict HH:MM only (one colon, no seconds), 24-hour wall clock. */
export function parseHHMMStrict(s: string): number | null {
    const str = s.trim()
    if (str.split(':').length !== 2) {
        return null
    }
    const [hs, ms] = str.split(':')
    if (!/^\d{1,2}$/.test(hs) || !/^\d{1,2}$/.test(ms)) {
        return null
    }
    const h = parseInt(hs, 10)
    const m = parseInt(ms, 10)
    if (Number.isNaN(h) || Number.isNaN(m) || h < 0 || h > 23 || m < 0 || m > 59) {
        return null
    }
    return h * 60 + m
}

function mergeIntervalsSorted(intervals: [number, number][]): [number, number][] {
    if (intervals.length === 0) {
        return []
    }
    const sorted = [...intervals].sort((a, b) => a[0] - b[0] || a[1] - b[1])
    const merged: [number, number][] = []
    for (const [a, b] of sorted) {
        if (b <= a) {
            continue
        }
        if (merged.length === 0 || merged[merged.length - 1][1] < a) {
            merged.push([a, b])
        } else {
            const [pa, pb] = merged[merged.length - 1]
            merged[merged.length - 1] = [pa, Math.max(pb, b)]
        }
    }
    return merged
}

function expandForCoverage(parsed: ParsedSegment[]): [number, number][] | null {
    const out: [number, number][] = []
    for (const { start, end, overnight } of parsed) {
        if (!overnight) {
            if (start < end) {
                out.push([start, end])
            } else {
                return null
            }
        } else if (end === 0) {
            out.push([start, MINUTES_PER_DAY])
        } else {
            out.push([start, MINUTES_PER_DAY])
            out.push([0, end])
        }
    }
    return out
}

function mergedCoversFullDay(merged: [number, number][]): boolean {
    return merged.length > 0 && merged[0][0] === 0 && merged[0][1] >= MINUTES_PER_DAY
}

/** Half-open complement of blocked intervals within [0, dayLen). Assumes `blocked` merged and sorted. */
export function complementMinuteIntervals(
    blocked: [number, number][],
    dayLen: number = MINUTES_PER_DAY
): [number, number][] {
    if (blocked.length === 0) {
        return [[0, dayLen]]
    }
    const allowed: [number, number][] = []
    let cursor = 0
    const sorted = [...blocked].sort((a, b) => a[0] - b[0] || a[1] - b[1])
    for (const [a, b] of sorted) {
        if (b <= a) {
            continue
        }
        if (cursor < a) {
            allowed.push([cursor, a])
        }
        cursor = Math.max(cursor, b)
    }
    if (cursor < dayLen) {
        allowed.push([cursor, dayLen])
    }
    return allowed
}

type MergeBlockedResult = { merged: [number, number][] } | { issue: QuietHoursIssue }

/** Shared parse + merge (same rules as form validation). */
export function mergeBlockedWindowsOrIssue(windows: BlockedWindow[]): MergeBlockedResult {
    if (windows.length > MAX_BLOCKED_WINDOWS) {
        return {
            issue: {
                kind: 'form',
                message: `At most ${MAX_BLOCKED_WINDOWS} time windows for quiet hours per alert`,
            },
        }
    }

    const parsed: ParsedSegment[] = []
    for (let i = 0; i < windows.length; i++) {
        const { start, end } = windows[i]
        const sm = parseHHMMStrict(start)
        if (sm === null) {
            return { issue: { kind: 'row', index: i, message: 'Use a valid start time (HH:MM, 24-hour, no seconds).' } }
        }
        const em = parseHHMMStrict(end)
        if (em === null) {
            return { issue: { kind: 'row', index: i, message: 'Use a valid end time (HH:MM, 24-hour, no seconds).' } }
        }
        if (sm === em) {
            return { issue: { kind: 'row', index: i, message: 'Start and end must differ.' } }
        }
        const overnight = sm > em
        const span = blockedWindowSpanMinutes(sm, em, overnight)
        if (span < MIN_BLOCKED_WINDOW_MINUTES) {
            return {
                issue: {
                    kind: 'row',
                    index: i,
                    message: `Each quiet hours window must span at least ${MIN_BLOCKED_WINDOW_MINUTES} minutes.`,
                },
            }
        }
        parsed.push({ start: sm, end: em, overnight })
    }

    const expanded = expandForCoverage(parsed)
    if (!expanded) {
        return { issue: { kind: 'form', message: 'Invalid time windows for quiet hours.' } }
    }

    const merged = mergeIntervalsSorted(expanded)
    if (mergedCoversFullDay(merged)) {
        return {
            issue: {
                kind: 'form',
                message: 'Leave at least one time in the day when this alert can run.',
            },
        }
    }

    return { merged }
}

/** Single parse/merge for timeline UI: blocked + allowed minutes in [0, MINUTES_PER_DAY). */
export function blockedAndAllowedMinuteIntervalsForQuietHours(
    windows: BlockedWindow[]
): { blocked: [number, number][]; allowed: [number, number][] } | null {
    if (windows.length === 0) {
        return null
    }
    const result = mergeBlockedWindowsOrIssue(windows)
    if ('issue' in result) {
        return null
    }
    const blocked = result.merged
    return { blocked, allowed: complementMinuteIntervals(blocked) }
}

/** Merged quiet (blocked) intervals for one local day, or `null` if windows are invalid for save. */
export function mergedBlockedIntervalsForQuietHours(windows: BlockedWindow[]): [number, number][] | null {
    return blockedAndAllowedMinuteIntervalsForQuietHours(windows)?.blocked ?? null
}

/** Minutes of the local day when the alert may run (complement of quiet hours), or `null` if invalid. */
export function allowedLocalMinuteIntervalsForQuietHours(windows: BlockedWindow[]): [number, number][] | null {
    return blockedAndAllowedMinuteIntervalsForQuietHours(windows)?.allowed ?? null
}

function blockedWindowSpanMinutes(start: number, end: number, overnight: boolean): number {
    if (!overnight) {
        return end - start
    }
    if (end === 0) {
        return MINUTES_PER_DAY - start
    }
    return MINUTES_PER_DAY - start + end
}

export function findQuietHoursIssues(windows: BlockedWindow[]): QuietHoursIssue | null {
    if (windows.length === 0) {
        return null
    }
    const result = mergeBlockedWindowsOrIssue(windows)
    return 'issue' in result ? result.issue : null
}

/** First error message for kea-forms `errors`, or undefined if valid / feature off. */
export function quietHoursFormError(scheduleRestriction: ScheduleRestriction | null | undefined): string | undefined {
    const windows = scheduleRestriction?.blocked_windows
    if (!windows?.length) {
        return undefined
    }
    const issue = findQuietHoursIssues(windows)
    return issue?.message
}
