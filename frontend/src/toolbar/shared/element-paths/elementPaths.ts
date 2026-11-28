import type { CommonFilters } from 'lib/components/heatmaps/types'

import { urls } from '~/toolbar/shared/urls'
import type { ActionStepType } from '~/types'

import type { ElementPath, ElementPathsParams, ElementPathsResult } from './elementPathsApiTypes'

// The endpoint refuses a range longer than this with a 400.
const MAX_RANGE_DAYS = 31
const FALLBACK_RANGE: ElementPathsDateRange = { dateFrom: '-30d', label: 'in the last 30 days' }
const RELATIVE_DATE = /^-(\d+)([hd])$/
const CALENDAR_RANGES: Record<string, string> = { dStart: 'today', '-1dStart': 'since yesterday', mStart: 'this month' }

export interface ElementPathsDateRange {
    dateFrom: string
    /** Ends a sentence, so it is lowercase and carries its own preposition: "in the last 7 days", "today". */
    label: string
}

/** One resolved answer for one element. Plain data, because the extension sends it to the panel. */
export type ElementPathsView =
    | { status: 'idle' }
    | { status: 'loading' }
    /** The project doesn't have user journeys, so the section stays hidden. */
    | { status: 'unavailable' }
    | { status: 'error' }
    | { status: 'no-clicks' | 'no-shared-path' | 'paths'; result: ElementPathsResult; rangeLabel: string }

/**
 * Follows the heatmap's date range when the endpoint accepts it. A longer or absolute range falls back to the last
 * 30 days, and the section says which range it shows.
 */
export function elementPathsDateRange(
    commonFilters: Pick<CommonFilters, 'date_from' | 'date_to'>
): ElementPathsDateRange {
    const { date_from: dateFrom, date_to: dateTo } = commonFilters
    if (!dateFrom || dateTo) {
        return FALLBACK_RANGE
    }
    if (dateFrom in CALENDAR_RANGES) {
        return { dateFrom, label: CALENDAR_RANGES[dateFrom] }
    }
    const match = RELATIVE_DATE.exec(dateFrom)
    if (!match) {
        return FALLBACK_RANGE
    }
    const amount = Number(match[1])
    const unit = match[2] === 'h' ? 'hour' : 'day'
    const days = unit === 'hour' ? amount / 24 : amount
    if (amount < 1 || days > MAX_RANGE_DAYS) {
        return FALLBACK_RANGE
    }
    return { dateFrom, label: amount === 1 ? `in the last ${unit}` : `in the last ${amount} ${unit}s` }
}

function escapeRegex(value: string): string {
    return value.replace(/[\\^$.*+?()[\]{}|]/g, '\\$&')
}

/** Matches the page with any trailing slash, query string or hash, as `$current_url` records them. */
export function pageUrlRegex(url: string): string {
    return `^${escapeRegex(url.replace(/\/+$/, ''))}/*(?:[?#].*)?$`
}

export function elementPathsQuery(
    actionStep: ActionStepType | null | undefined,
    commonFilters: CommonFilters
): ElementPathsParams | null {
    const selector = actionStep?.selector?.trim()
    if (!actionStep || !selector) {
        return null
    }
    return {
        selector,
        ...(actionStep.text ? { text: actionStep.text } : {}),
        ...(actionStep.href ? { href: actionStep.href } : {}),
        ...(actionStep.url ? { url: pageUrlRegex(actionStep.url), url_matching: 'regex' as const } : {}),
        date_from: elementPathsDateRange(commonFilters).dateFrom,
        filter_test_accounts: !!commonFilters.filter_test_accounts,
    }
}

export function resolvedElementPathsStatus(
    result: ElementPathsResult
): Extract<ElementPathsView, { result: ElementPathsResult }>['status'] {
    if (result.anchor_click_count === 0) {
        return 'no-clicks'
    }
    return result.paths.length === 0 ? 'no-shared-path' : 'paths'
}

/** A path in the app's create form, prefilled. Prefix it with the project's app URL to open it. */
export function saveAsJourneyPath(path: ElementPath): string {
    const anchor = path.nodes[path.anchor_index]
    return urls.userJourneyNew({
        name: anchor ? `Path through ${anchor.label}` : undefined,
        steps: path.nodes.map((node) => node.step),
        source: 'toolbar',
    })
}
