import { urls } from 'scenes/urls'

import type { TodayReportCard } from '~/layout/today/todayPreviewCards'

import type {
    BriefingApi,
    BriefingItemApi,
    BriefingItemStateEnumApi,
    TodayItemReasonEnumApi,
} from 'products/today/frontend/generated/api.schemas'

import { TodayReportSource, sourceStyle } from './todaySignalReports'

/** Where an item was opened from, sent with the `today item opened` event. */
export type TodayItemOpenSurface = 'briefing' | 'chip' | 'sidebar'

/** A report takes the style of the product its signals came from, the way the inbox shows it. */
export function itemSource(item: Pick<BriefingItemApi, 'source' | 'source_product'>): TodayReportSource {
    return sourceStyle(item.source_product ?? item.source)
}

const REASON_LABELS: Record<TodayItemReasonEnumApi, string> = {
    claimed_by_you: 'You claimed it',
    waiting_for_you: 'Waiting for your input',
    suggested_reviewer: 'You are a suggested reviewer',
    urgent_for_project: 'Urgent, and nobody owns it',
    dashboard_you_viewed: 'A dashboard you viewed',
    dashboard_you_starred: 'A dashboard you starred',
    insight_you_viewed: 'An insight you viewed',
    insight_you_starred: 'An insight you starred',
    alert_firing: 'An alert you follow is firing',
    assigned_ticket: 'Assigned to you',
    assigned_error_issue: 'Assigned to you or your role',
    review_requested: 'Your review was requested',
    your_pull_request: 'Your pull request',
}

/** Why the briefing picked the item, as the hover card says it. */
export function itemReasonLabel(item: Pick<BriefingItemApi, 'reason'>): string {
    return REASON_LABELS[item.reason]
}

const STATE_LABELS: Record<BriefingItemStateEnumApi, string | null> = {
    open: null,
    done: 'Resolved',
    dismissed: 'Dismissed',
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

export function briefingItemReportCard(item: BriefingItemApi): TodayReportCard {
    return {
        key: item.key,
        reportId: itemReportId(item),
        title: item.title,
        reason: itemReasonLabel(item),
        stateLabel: itemStateLabel(item),
        resolved: item.state === 'done',
        priority: item.report?.priority ?? null,
        summary: item.report?.summary || null,
        pullRequestState: item.report?.pull_request_state ?? null,
        pullRequestUrl: item.report?.pull_request_url ?? null,
        signalCount: item.report?.signal_count ?? null,
        updatedAt: item.report?.updated_at ?? null,
        metrics: item.report?.metrics ?? [],
        charts: item.report?.charts ?? [],
        sourceLabel: itemSource(item).label,
    }
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
