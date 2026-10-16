import { urls } from 'scenes/urls'

import type {
    BriefingApi,
    BriefingItemApi,
    BriefingItemStateEnumApi,
} from 'products/today/frontend/generated/api.schemas'

const STATE_LABELS: Record<BriefingItemStateEnumApi, string | null> = {
    open: null,
    done: 'Resolved',
    dismissed: 'Dismissed',
    left: 'Not yours',
}

/** What happened to the item since the briefing was written, or null while it is still open. */
export function itemStateLabel(item: Pick<BriefingItemApi, 'state'>): string | null {
    return STATE_LABELS[item.state]
}

const REPORT_STATUS_STATES: Record<string, BriefingItemStateEnumApi> = {
    resolved: 'done',
    suppressed: 'dismissed',
    deleted: 'dismissed',
}

/** A report's status in the briefing's terms, the way the backend gives briefing items their live state. */
export function reportItemState(status: string): BriefingItemStateEnumApi {
    return REPORT_STATUS_STATES[status] ?? 'open'
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

export function isBriefingSettled(briefing: Pick<BriefingApi, 'status'>): boolean {
    return briefing.status === 'ready' || briefing.status === 'failed'
}
