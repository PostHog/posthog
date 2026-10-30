import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { HighlightItemApi } from 'products/today/frontend/generated/api.schemas'

import type { TodayForYouRow } from './todayForYouRows'
import type { TodayFeedCardEvent } from './todayLogic'
import { sourceStyle } from './todaySignalReports'

// Highlights whose product is Today itself, so the product name says nothing about where they came from.
const TODAY_SOURCE_LABELS: Record<string, string> = {
    home: 'Your insights',
    routine: 'Your insights',
    key_metrics: 'Key metrics',
}

const HIGHLIGHT_ACTION_LABELS: Record<string, string> = {
    alerts: 'View alert',
    errors: 'View errors',
    ticket_sla: 'Reply to ticket',
    rage: 'Watch recordings',
    flags: 'Review flag',
    workflows: 'Open workflow',
    workflow_ideas: 'Review changes',
    experiments: 'Open experiment',
    data_catalog_approvals: 'Review suggestions',
    warehouse_model_suggestions: 'Review suggestions',
    home: 'Open insight',
    routine: 'Open insight',
    key_metrics: 'Open insight',
}

// The trailing window phrases the highlight sources write, so a one-line title can show them as metadata.
const TRAILING_PERIOD = / (in the last \d+ days|within 24 hours|last week|last month|yesterday)$/
// A quoted name long enough to push the rest of a one-line title out of view, such as an error message.
const LONG_QUOTE = /^(.+?) ‘(.{24,})’$/

export interface TodayFeedTitle {
    title: string
    quote: string | null
    period: string | null
}

export function highlightSourceLabel(item: Pick<HighlightItemApi, 'source' | 'product'>): string {
    return TODAY_SOURCE_LABELS[item.source] ?? sourceStyle(item.product).label
}

export function highlightActionLabel(source: string): string {
    return HIGHLIGHT_ACTION_LABELS[source] ?? 'View'
}

export function feedRowSource(row: TodayForYouRow): string {
    return row.kind === 'report' ? sourceStyle(row.report.source_products?.[0]).label : highlightSourceLabel(row.item)
}

export function feedCardEvent(row: TodayForYouRow, position: number): TodayFeedCardEvent {
    return {
        kind: row.kind,
        key: row.key,
        source: feedRowSource(row),
        position,
        priority: (row.kind === 'report' ? row.report.priority : row.item.priority) ?? null,
    }
}

export function splitHighlightTitle(text: string): TodayFeedTitle {
    const period = text.match(TRAILING_PERIOD)
    const title = period ? text.slice(0, period.index) : text
    const quote = title.match(LONG_QUOTE)
    return {
        title: quote ? quote[1] : title,
        quote: quote ? quote[2] : null,
        period: period ? capitalizeFirstLetter(period[1].replace(/^in the /, '')) : null,
    }
}
