import { Dayjs, dayjs } from 'lib/dayjs'
import { ViewItem } from 'scenes/views/viewsUtils'

import { dayLabel } from './todayWorkItems'

// pinned: these values are the `group_by` property of the `views sidebar filtered` event.
export type TodayViewsGrouping = 'date' | 'none'

export const DEFAULT_VIEWS_GROUPING: TodayViewsGrouping = 'date'

export const VIEWS_GROUPING_OPTIONS: { value: TodayViewsGrouping; label: string }[] = [
    { value: 'date', label: 'Date' },
    { value: 'none', label: 'None' },
]

export interface TodayViewsRow {
    item: ViewItem
    /** The loaded investigations of the same alert that this row stands for, the shown one included. 1 for other views. */
    count: number
}

export interface TodayViewsSection {
    key: string
    /** Null when the list has no grouping. */
    label: string | null
    rows: TodayViewsRow[]
}

/**
 * One row per alert for its investigations, at the place of the newest one. The list is newest first,
 * so a later page that brings in older investigations of the same alert raises the count but never moves the row.
 */
export function viewRows(items: ViewItem[], stackInvestigations: boolean): TodayViewsRow[] {
    const rows: TodayViewsRow[] = []
    const rowsByAlert = new Map<string, TodayViewsRow>()
    for (const item of items) {
        const alertId = stackInvestigations ? item.alertInvestigation?.alertId : undefined
        const stacked = alertId ? rowsByAlert.get(alertId) : undefined
        if (stacked) {
            stacked.count += 1
            continue
        }
        const row = { item, count: 1 }
        rows.push(row)
        if (alertId) {
            rowsByAlert.set(alertId, row)
        }
    }
    return rows
}

/** Cuts the newest-first rows into one section per day. */
export function groupViewRows(
    rows: TodayViewsRow[],
    grouping: TodayViewsGrouping,
    now: Dayjs = dayjs()
): TodayViewsSection[] {
    if (grouping === 'none') {
        return rows.length ? [{ key: 'all', label: null, rows }] : []
    }
    const sections: TodayViewsSection[] = []
    for (const row of rows) {
        // A clock ahead of this browser can stamp a view in the future, which still belongs to today.
        const stamped = row.item.timestamp ? dayjs(row.item.timestamp) : null
        const time = stamped?.isAfter(now) ? now : stamped
        const key = time ? time.format('YYYY-MM-DD') : 'undated'
        const last = sections[sections.length - 1]
        if (last?.key === key) {
            last.rows.push(row)
        } else {
            sections.push({ key, label: time ? dayLabel(time, now) : 'Earlier', rows: [row] })
        }
    }
    return sections
}
