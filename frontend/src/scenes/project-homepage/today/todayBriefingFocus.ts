import type { SignalReport } from 'products/signals/frontend/inbox/types'
import type { BriefingItemApi } from 'products/today/frontend/generated/api.schemas'

import { lowerFirst, sourceLabel } from './todaySignalReports'

/** Whether the person wants more or less of a topic in their briefing. A topic with no direction is ranked as usual. */
export type TodayFocusDirection = 'more' | 'less'

/** How long a saved focus holds. A focus for this week goes back to normal ranking after seven days. */
export type TodayFocusDuration = 'week' | 'always'

export interface TodayBriefingFocus {
    /** Keyed by source product, the way reports name the product their signals came from. */
    topics: Record<string, TodayFocusDirection>
    duration: TodayFocusDuration
    /** ISO time after which the focus no longer applies, or null when it holds until the person changes it. */
    until: string | null
}

export interface TodayFocusTopic {
    key: string
    label: string
}

export const EMPTY_FOCUS: TodayBriefingFocus = { topics: {}, duration: 'week', until: null }

const WEEK_MS = 7 * 24 * 60 * 60 * 1000

// Offered even when the person's own reports name none of them, so a new person has something to pick.
const DEFAULT_TOPICS = ['error_tracking', 'session_replay', 'analytics', 'llm_analytics', 'surveys', 'logs']

export const MAX_FOCUS_TOPICS = 8

export function focusUntil(duration: TodayFocusDuration, now: number): string | null {
    return duration === 'week' ? new Date(now + WEEK_MS).toISOString() : null
}

/** The saved focus, or the empty one when it has expired. */
export function activeFocus(focus: TodayBriefingFocus, now: number): TodayBriefingFocus {
    return focus.until && Date.parse(focus.until) <= now ? EMPTY_FOCUS : focus
}

export function hasFocus(focus: TodayBriefingFocus): boolean {
    return Object.keys(focus.topics).length > 0
}

/**
 * The topics the focus dialog offers: the ones already in the focus, then the products the person's own
 * briefing items and reports come from, then common products, up to `MAX_FOCUS_TOPICS`.
 */
export function focusTopics(
    focus: TodayBriefingFocus,
    briefingItems: Pick<BriefingItemApi, 'source_product'>[],
    reports: Pick<SignalReport, 'source_products'>[]
): TodayFocusTopic[] {
    const keys = [
        ...Object.keys(focus.topics),
        ...briefingItems.flatMap((item) => (item.source_product ? [item.source_product] : [])),
        ...reports.flatMap((report) => report.source_products ?? []),
        ...DEFAULT_TOPICS,
    ]
    // Some products share a label, such as `analytics` and `product_analytics`, so one row stands for both.
    const byLabel = new Map<string, TodayFocusTopic>()
    for (const key of keys) {
        const label = sourceLabel(key)
        if (!byLabel.has(label)) {
            byLabel.set(label, { key, label })
        }
    }
    return [...byLabel.values()].slice(0, MAX_FOCUS_TOPICS)
}

/** The line under the greeting, for example "Focused on Error tracking and Logs, less Surveys". */
export function focusSummary(focus: TodayBriefingFocus): string {
    const labels = (direction: TodayFocusDirection): string[] =>
        Object.entries(focus.topics)
            .filter(([, value]) => value === direction)
            .map(([key]) => sourceLabel(key))
    const more = labels('more')
    const less = labels('less').map(lowerFirst)
    const parts = [
        more.length > 0 ? `Focused on ${joinWithAnd(more)}` : null,
        less.length > 0 ? `${more.length > 0 ? 'less' : 'Less'} ${joinWithAnd(less)}` : null,
    ]
    return parts.filter(Boolean).join(', ')
}

function joinWithAnd(labels: string[]): string {
    return labels.length <= 1 ? labels.join('') : `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`
}
