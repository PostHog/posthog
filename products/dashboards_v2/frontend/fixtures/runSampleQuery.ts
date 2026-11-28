import { PropertyOperator } from '~/types'

import { type AnalyticsPropertyFilter, analyticsPropertyFilters } from '../filters/analytics/analyticsPropertyFilters'
import type { DataFrame, RunQuery } from '../query/queryTypes'
import { type PanelQuery } from '../query/querySchema'

// TODO(2026-11-25): Delete once the scene always runs real queries through the query batch runner.
// Without both v2 query flags, the scene draws charts from these seeded sample frames.

const DAYS = 14

function seededRandom(seed: string): () => number {
    let state = [...seed].reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 2166136261)
    return () => {
        state = (state * 1664525 + 1013904223) >>> 0
        return state / 2 ** 32
    }
}

function queryText(query: PanelQuery): string {
    return typeof query.query === 'string' ? query.query : JSON.stringify(query.query)
}

function seriesNames(query: PanelQuery): string[] {
    return / by (?!day\b)|by day, |breakdown|sum by|serviceNames/.test(queryText(query))
        ? ['Chrome', 'Safari', 'Firefox']
        : ['Value']
}

// A rate drawn as a count reads as 272,300% on a percentage metric.
function isRatio(query: PanelQuery): boolean {
    return /_rate\b/.test(queryText(query))
}

// Only "is" and "is not" on the browser narrow the sample series, which is enough to see a filter apply.
function keepsSeries(filter: AnalyticsPropertyFilter, name: string): boolean {
    if (!Array.isArray(filter.value)) {
        return true
    }
    const listed = filter.value.map(String).includes(name)
    if (filter.operator === PropertyOperator.IsNot) {
        return !listed
    }
    return filter.operator === PropertyOperator.Exact ? listed : true
}

/**
 * A `-- sample: <case>` comment in a query's text picks how the sample runner answers, so the kitchen sink can show
 * every tile state. The queries that carry one fail or come back empty on the real runner too.
 */
export type SampleCase = 'empty' | 'error' | 'slow' | 'loading' | 'stale' | 'malformed'

const SLOW_MS = 4000

function sampleCase(query: PanelQuery): SampleCase | null {
    const match = /-- sample: (empty|error|slow|loading|stale|malformed)/.exec(queryText(query))
    return match ? (match[1] as SampleCase) : null
}

// Draws charts for people outside the dashboard-v2 query flags, and for stories. The data is made up from each
// query's text, so the same query always draws the same chart.
export const runSampleQuery: RunQuery = async (request, signal) => {
    switch (sampleCase(request.query)) {
        case 'empty':
            return { frames: [{ fields: [{ name: 'value', type: 'number', values: [] }] }] }
        case 'error':
            throw new Error('Unable to resolve field: missing_column')
        case 'malformed':
            // A runner that breaks its contract, so the panel throws and its error boundary catches it.
            return { frames: [{ name: 'Broken' } as DataFrame] }
        case 'slow':
            await new Promise((resolve) => setTimeout(resolve, SLOW_MS))
            return sampleFrames(request)
        case 'loading':
            // Never answers, so the tile keeps its loading skeleton.
            return new Promise((_, reject) =>
                signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
            )
        case 'stale':
            return { ...sampleFrames(request), fetchedAt: '2026-11-20T09:00:00Z', stale: true }
        default:
            return sampleFrames(request)
    }
}

function sampleFrames({ query, time, legend, filters = [] }: Parameters<RunQuery>[0]): { frames: DataFrame[] } {
    const random = seededRandom(JSON.stringify({ query, time, filters }))
    const browser = analyticsPropertyFilters(filters).filter((filter) => filter.key === '$browser')
    const today = new Date('2026-11-23T00:00:00Z')
    const days = Array.from({ length: DAYS }, (_, index) => {
        const day = new Date(today)
        day.setUTCDate(today.getUTCDate() - (DAYS - 1 - index))
        return day.toISOString().slice(0, 10)
    })
    const base = 200 + Math.round(random() * 2000)
    const names = seriesNames(query)
    const shown = names.length > 1 ? names.filter((name) => browser.every((filter) => keepsSeries(filter, name))) : names
    const frames = shown.map(
        (name, position): DataFrame => ({
            name: legend ? legend.replace(/\{\{\s*[\w.]+\s*\}\}/g, name) : name,
            fields: [
                { name: 'time', type: 'time', values: days },
                {
                    name: 'value',
                    type: 'number',
                    values: days.map((_, index) =>
                        isRatio(query)
                            ? +(0.05 + 0.3 * random()).toFixed(3)
                            : Math.round((base / (position + 1)) * (0.75 + 0.5 * random()) * (1 + index / (DAYS * 2)))
                    ),
                },
            ],
        })
    )
    return { frames }
}
