import type { UncoveredGroupApi, UsageSnapshotPayloadApi } from './generated/api.schemas'

export interface MetricUsageRow {
    metricId: string
    name: string
    directRuns: number
    surfaces: [string, number][]
    people: number
    adapted: number
    missed: number
    silent: number
}

// Scout runs are counted on the server but only added here when the viewer asks for them, because
// one scheduled agent can run a metric many times a day and hide every other surface.
const SCOUT_SURFACE = 'scouts'

export function buildMetricUsageRows(
    payload: UsageSnapshotPayloadApi,
    metricNames: Record<string, string>,
    includeScouts: boolean
): MetricUsageRow[] {
    const rows = new Map<string, MetricUsageRow>()
    const rowFor = (metricId: string): MetricUsageRow => {
        let row = rows.get(metricId)
        if (!row) {
            row = {
                metricId,
                name: metricNames[metricId] ?? metricId,
                directRuns: 0,
                surfaces: [],
                people: 0,
                adapted: 0,
                missed: 0,
                silent: 0,
            }
            rows.set(metricId, row)
        }
        return row
    }

    for (const counts of payload.metric_runs ?? []) {
        const row = rowFor(counts.metric_id)
        const surfaces: [string, number][] = Object.entries(counts.direct_runs)
        if (includeScouts && counts.scout_runs > 0) {
            surfaces.push([SCOUT_SURFACE, counts.scout_runs])
        }
        row.surfaces = surfaces.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        row.directRuns = surfaces.reduce((total, [, runs]) => total + runs, 0)
        row.people = counts.direct_people
    }

    for (const run of payload.adjusted_runs ?? []) {
        if (run.is_scout && !includeScouts) {
            continue
        }
        const row = rowFor(run.metric_id)
        if (run.fetch_outcome === 'adapted') {
            row.adapted += 1
        } else if (run.fetch_outcome === 'missed') {
            row.missed += 1
        } else {
            row.silent += 1
        }
    }

    return [...rows.values()].sort(
        (a, b) =>
            b.directRuns + b.adapted + b.missed + b.silent - (a.directRuns + a.adapted + a.missed + a.silent) ||
            a.name.localeCompare(b.name)
    )
}

export function uncoveredRuns(group: UncoveredGroupApi, includeScouts: boolean): number {
    return group.runs + (includeScouts ? group.scout_runs : 0)
}
