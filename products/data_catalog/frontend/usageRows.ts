import type { TopicSessionCountsApi, UsageSnapshotPayloadApi } from './generated/api.schemas'

export interface SourceRow {
    key: string
    kind: 'metric' | 'table'
    name: string
    /** Runs for a metric, sessions for a table. */
    uses: number
    people: number
    surfaces: [string, number][]
}

const SOURCES_SHOWN_PER_KIND = 3
const SHOWN_ROWS = 25

// Scout runs stay out, because one scheduled agent can run a metric many times a day and hide every other surface.
export function buildSourceRows(payload: UsageSnapshotPayloadApi, metricNames: Record<string, string>): SourceRow[] {
    const metrics = (payload.metric_runs ?? []).map((counts): SourceRow => {
        const surfaces: [string, number][] = Object.entries(counts.direct_runs)
        surfaces.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        return {
            key: `metric-${counts.metric_id}`,
            kind: 'metric',
            name: metricNames[counts.metric_id] ?? counts.metric_id,
            uses: surfaces.reduce((total, [, runs]) => total + runs, 0),
            people: counts.direct_people,
            surfaces,
        }
    })
    const tables = (payload.table_sources ?? []).map(
        (table): SourceRow => ({
            key: `table-${table.name}`,
            kind: 'table',
            name: table.name,
            uses: table.sessions,
            people: table.people,
            surfaces: [],
        })
    )
    const ranked = (rows: SourceRow[]): SourceRow[] =>
        [...rows].sort((a, b) => b.people - a.people || b.uses - a.uses || a.name.localeCompare(b.name))
    const rankedMetrics = ranked(metrics.filter((row) => row.uses > 0))
    const rankedTables = ranked(tables)
    // Metrics reach far more people, so a shared ranking alone would push every table off the first page.
    return [
        ...ranked([
            ...rankedMetrics.slice(0, SOURCES_SHOWN_PER_KIND),
            ...rankedTables.slice(0, SOURCES_SHOWN_PER_KIND),
        ]),
        ...ranked([...rankedMetrics.slice(SOURCES_SHOWN_PER_KIND), ...rankedTables.slice(SOURCES_SHOWN_PER_KIND)]),
    ].slice(0, SHOWN_ROWS)
}

export function describeTopicSessions(counts: TopicSessionCountsApi): string {
    const sampled = counts.analysis + counts.lookup + counts.automation + counts.unclear + counts.unread
    const leftOut = [
        [counts.lookup, 'lookups'],
        [counts.automation, 'scheduled jobs'],
        [counts.unclear, 'unclear'],
        [counts.unread, 'could not be read'],
    ]
        .filter(([count]) => count)
        .map(([count, label]) => `${count} ${label}`)
    const summary = `These topics cover the ${counts.analysis} of ${sampled} sampled sessions that analyzed data.`
    const unchecked = counts.coverage_unchecked
        ? ` Coverage could not be checked for ${counts.coverage_unchecked} of them.`
        : ''
    return leftOut.length ? `${summary}${unchecked} Left out: ${leftOut.join(', ')}.` : `${summary}${unchecked}`
}
