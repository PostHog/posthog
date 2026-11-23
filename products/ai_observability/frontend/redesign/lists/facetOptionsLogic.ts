import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import type { FacetOptions } from './facetFilters'
import { hogqlRows } from './listQuery'

// ponytail: a fixed 30-day window rather than each page's range, so the options don't jump as the range changes.
const WINDOW = { propertyFilters: [], filterTestAccounts: false, dateFrom: '-30d', dateTo: null }

function topValues(expr: string): string {
    return `SELECT ${expr} AS value, count() AS calls
        FROM events
        WHERE event = '$ai_generation' AND {filters}
        GROUP BY value
        HAVING notEmpty(value)
        ORDER BY calls DESC
        LIMIT 200`
}

async function values(expr: string): Promise<string[]> {
    const rows = await hogqlRows<{ value: string }>(topValues(expr), WINDOW)
    return rows.map((row) => row.value)
}

async function slowThresholdSeconds(): Promise<number | null> {
    const [row] = await hogqlRows<{ p95: number | null }>(
        `SELECT quantile(0.95)(toFloat(properties.$ai_latency)) AS p95
        FROM events
        WHERE event = '$ai_generation' AND {filters}`,
        WINDOW
    )
    return row?.p95 && Number.isFinite(row.p95) ? Math.round(row.p95 * 100) / 100 : null
}

export const facetOptionsLogic = kea([
    path(['products', 'ai_observability', 'frontend', 'redesign', 'lists', 'facetOptionsLogic']),
    loaders({
        options: [
            null as FacetOptions | null,
            {
                loadOptions: async (): Promise<FacetOptions> => {
                    const [models, providers, tools, slow] = await Promise.all([
                        values('toString(properties.$ai_model)'),
                        values('toString(properties.$ai_provider)'),
                        values("arrayJoin(splitByChar(',', ifNull(toString(properties.$ai_tools_called), '')))"),
                        slowThresholdSeconds(),
                    ])
                    return { models, providers, tools, slowThresholdSeconds: slow }
                },
            },
        ],
    }),
    afterMount(({ actions, values }) => {
        if (!values.options) {
            actions.loadOptions()
        }
    }),
])
