import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import type { HighlightItemApi } from 'products/today/frontend/generated/api.schemas'

export const VISIBLE_ROWS = 5

export type TodayForYouRow =
    | { kind: 'report'; key: string; report: SignalReport; source: 'list' | 'more'; done: boolean }
    | { kind: 'highlight'; key: string; item: HighlightItemApi; position: number; done: boolean }
    | { kind: 'product_push'; key: string; campaign: ProductPushCampaignApi; done: false }

/** Where the product push sits: among the rows shown at first, or first among the rows "Show more" adds. */
export type ProductPushSlot = 'visible' | 'expanded'

export interface TodayProductPush {
    campaign: ProductPushCampaignApi
    slot: ProductPushSlot
}

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
    productPush?: TodayProductPush | null
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
    const limit = base.length <= VISIBLE_ROWS + 1 ? base.length : VISIBLE_ROWS
    return withProductPush({ rows: [...base, ...moreRows], limit }, input.productPush ?? null)
}

// The push is an extra row: it never takes the place of a fact. It joins a list that has rows, and the
// expanded slot exists only when the list has rows beyond the limit.
function withProductPush({ rows, limit }: TodayForYouRows, productPush: TodayProductPush | null): TodayForYouRows {
    if (!productPush || rows.length === 0) {
        return { rows, limit }
    }
    const row: TodayForYouRow = {
        kind: 'product_push',
        key: `product_push:${productPush.campaign.id}`,
        campaign: productPush.campaign,
        done: false,
    }
    if (productPush.slot === 'visible') {
        const middle = Math.ceil(limit / 2)
        return { rows: [...rows.slice(0, middle), row, ...rows.slice(middle)], limit: limit + 1 }
    }
    if (rows.length > limit) {
        return { rows: [...rows.slice(0, limit), row, ...rows.slice(limit)], limit }
    }
    return { rows, limit }
}

/** Half of a person's days put the push among the first rows, the other half behind "Show more". */
export function productPushSlot(campaignId: string, userId: string, day: string): ProductPushSlot {
    const seed = `${campaignId}:${userId}:${day}`
    let hash = 0
    for (let index = 0; index < seed.length; index++) {
        hash = (Math.imul(hash, 31) + seed.charCodeAt(index)) | 0
    }
    return (hash >>> 0) % 2 === 0 ? 'visible' : 'expanded'
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
