import { urls } from 'scenes/urls'

import type { BriefingApi, BriefingItemApi } from 'products/today/frontend/generated/api.schemas'

import { TodayReportSource, sourceStyle } from './todaySignalReports'

/** Where an item was opened from, sent with the `today item opened` event. */
export type TodayItemOpenSurface = 'briefing' | 'chip' | 'sidebar'

/** A report takes the style of the product its signals came from, the way the inbox shows it. */
export function itemSource(item: Pick<BriefingItemApi, 'source' | 'source_product'>): TodayReportSource {
    return sourceStyle(item.source_product ?? item.source)
}

/** The report id of a `report:<id>` item, else null. */
export function itemReportId(item: Pick<BriefingItemApi, 'key'>): string | null {
    return item.key.startsWith('report:') ? item.key.slice('report:'.length) : null
}

/** Reports open in Today's own report page; every other item opens where it lives. */
export function itemHref(item: Pick<BriefingItemApi, 'key' | 'url'>): string {
    const reportId = itemReportId(item)
    return reportId ? urls.todayReport(reportId) : item.url
}

export function isExternalHref(href: string): boolean {
    return /^https?:\/\//.test(href)
}

/** The briefing has text to show. A briefing that failed before its draft has none. */
export function hasBriefingText(briefing: BriefingApi | null): boolean {
    return !!briefing && (!!briefing.headline || briefing.paragraphs.length > 0)
}

/** The briefing day the browser's clock is in. It matches the backend: a day starts at 8:00, so 7:59 is still yesterday. */
export function briefingDayKey(now: number): string {
    return new Date(now - 8 * 60 * 60 * 1000).toDateString()
}

export function isBriefingSettled(briefing: Pick<BriefingApi, 'status'>): boolean {
    return briefing.status === 'ready' || briefing.status === 'failed'
}
