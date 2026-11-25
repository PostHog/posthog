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

// TODO(2026-11-23): Replace this with a runner that sends queries through the dashboard-v2 query batch endpoint.
// The data is temporary. It is made up from each query's text, so the same query always draws the same chart.
export const runSampleQuery: RunQuery = async ({ query, time }) => {
    const random = seededRandom(JSON.stringify({ query, time }))
    const today = new Date('2026-11-23T00:00:00Z')
    const days = Array.from({ length: DAYS }, (_, index) => {
        const day = new Date(today)
        day.setUTCDate(today.getUTCDate() - (DAYS - 1 - index))
        return day.toISOString().slice(0, 10)
    })
    const base = 200 + Math.round(random() * 2000)
    const frames = seriesNames(query).map(
        (name, position): DataFrame => ({
            name,
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
