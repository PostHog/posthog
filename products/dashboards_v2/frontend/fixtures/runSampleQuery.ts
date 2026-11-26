import { PropertyOperator } from '~/types'

import { type AnalyticsPropertyFilter, analyticsPropertyFilters } from '../filters/analytics/analyticsPropertyFilters'
import type { DataFrame, RunQuery, WidgetQuery } from '../widgets/chart/vizTypes'

const DAYS = 14

function seededRandom(seed: string): () => number {
    let state = [...seed].reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 2166136261)
    return () => {
        state = (state * 1664525 + 1013904223) >>> 0
        return state / 2 ** 32
    }
}

function seriesNames(query: WidgetQuery): string[] {
    const text = typeof query.query === 'string' ? query.query : JSON.stringify(query.query)
    return / by (?!day)|breakdown|sum by|serviceNames/.test(text) ? ['Chrome', 'Safari', 'Firefox'] : ['Value']
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

// Draws charts for people outside the dashboard-v2 query flags, and for stories. The data is made up from each
// query's text, so the same query always draws the same chart.
export const runSampleQuery: RunQuery = async ({ query, time, legend, filters = [] }) => {
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
                        Math.round((base / (position + 1)) * (0.75 + 0.5 * random()) * (1 + index / (DAYS * 2)))
                    ),
                },
            ],
        })
    )
    return { frames }
}
