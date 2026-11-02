import { SignalReport } from 'products/signals/frontend/inbox/types'
import type { HighlightItemApi } from 'products/today/frontend/generated/api.schemas'

export const VISIBLE_ROWS = 5

export type TodayForYouRow =
    | { kind: 'report'; key: string; report: SignalReport; source: 'list' | 'more'; done: boolean }
    | { kind: 'highlight'; key: string; item: HighlightItemApi; position: number; done: boolean }

type TodayForYouReportRow = Extract<TodayForYouRow, { kind: 'report' }>

export interface TodayForYouRows {
    rows: TodayForYouRow[]
    limit: number
}

interface TodayForYouInput {
    reports: SignalReport[]
    loadedMoreReports: SignalReport[]
    highlights: HighlightItemApi[]
    doneHighlightKeys: string[]
    reportStateOverrides: Record<string, string>
}

export function rowReportId(row: TodayForYouRow): string | null {
    return row.kind === 'report' ? row.key : null
}

function reportRow(report: SignalReport, source: 'list' | 'more', overrides: Record<string, string>): TodayForYouRow {
    const state = overrides[report.id]
    return { kind: 'report', key: report.id, report, source, done: !!state && state !== 'open' }
}

export function forYouRows(input: TodayForYouInput): TodayForYouRows {
    const reportRows = input.reports.map((report) => reportRow(report, 'list', input.reportStateOverrides))
    const highlightRows: TodayForYouRow[] = input.highlights.map((item, position) => ({
        kind: 'highlight',
        key: item.key,
        item,
        position,
        done: input.doneHighlightKeys.includes(item.key),
    }))
    const base = [...reportRows, ...highlightRows]
    const moreRows = input.loadedMoreReports.map((report) => reportRow(report, 'more', input.reportStateOverrides))
    return { rows: [...base, ...moreRows], limit: base.length <= VISIBLE_ROWS + 1 ? base.length : VISIBLE_ROWS }
}

export function forYouReportIds(rows: TodayForYouRow[]): string[] {
    return rows.flatMap((row) => {
        const id = rowReportId(row)
        return id ? [id] : []
    })
}

export function reportRows(rows: TodayForYouRow[], source: 'list' | 'more'): TodayForYouReportRow[] {
    return rows.filter((row): row is TodayForYouReportRow => row.kind === 'report' && row.source === source)
}
