import { urls } from 'scenes/urls'

import type {
    BriefingApi,
    BriefingItemApi,
    TodayItemSourceEnumApi,
} from 'products/today/frontend/generated/api.schemas'

import { TodayReportSource, reportSource } from './todaySignalReports'

/** Where an item was opened from, sent with the `today item opened` event. */
export type TodayItemOpenSurface = 'briefing' | 'chip' | 'sidebar'

const ITEM_SOURCES: Record<TodayItemSourceEnumApi, TodayReportSource> = {
    self_driving: { label: 'Self-driving', color: 'var(--color-text-secondary)', icon: 'inbox' },
    product_analytics: {
        label: 'Product analytics',
        color: 'var(--color-product-product-analytics-light)',
        icon: 'analytics',
    },
    alerts: { label: 'Alerts', color: 'var(--color-product-product-analytics-light)', icon: 'trace' },
    support: { label: 'Support', color: 'var(--color-product-support-light)', icon: 'survey' },
    error_tracking: { label: 'Error tracking', color: 'var(--color-product-error-tracking-light)', icon: 'error' },
    github: { label: 'GitHub', color: 'var(--color-text-secondary)', icon: 'pr' },
}

/** A report takes the style of the product its signals came from, the way the inbox shows it. */
export function itemSource(item: Pick<BriefingItemApi, 'source' | 'source_product'>): TodayReportSource {
    if (item.source_product) {
        return reportSource({ source_products: [item.source_product] })
    }
    return ITEM_SOURCES[item.source] ?? ITEM_SOURCES.self_driving
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

/** The edition the browser's clock is in. It matches the backend: morning from 8:00, midday from 12:00. */
export function editionForHour(hour: number): BriefingApi['edition'] {
    return hour >= 8 && hour < 12 ? 'morning' : 'midday'
}

export function isBriefingSettled(briefing: Pick<BriefingApi, 'status'>): boolean {
    return briefing.status === 'ready' || briefing.status === 'failed'
}
