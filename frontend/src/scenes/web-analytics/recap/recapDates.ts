import type { WebAnalyticsRecapResponseApi } from 'products/web_analytics/frontend/generated/api.schemas'

function parseApiDate(date: string): Date {
    const [year, month, day] = date.split('-').map(Number)
    return new Date(year, month - 1, day)
}

function formatApiDate(date: string): string {
    return new Intl.DateTimeFormat(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    }).format(parseApiDate(date))
}

export function formatRecapDateRange(recap: Pick<WebAnalyticsRecapResponseApi, 'period_start' | 'period_end'>): string {
    return `${formatApiDate(recap.period_start)} - ${formatApiDate(recap.period_end)}`
}
