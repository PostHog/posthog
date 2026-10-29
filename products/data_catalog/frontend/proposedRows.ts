import type {
    ChartSourceApi,
    ProposedMetricApi,
    SurfaceSourceApi,
    AgentSourceApi,
    UsageSnapshotPayloadApi,
} from './generated/api.schemas'

const SHOWN_ROWS = 70

export interface ProposedRow {
    key: string
    /** The drafted name, or null when the measure has no draft yet. */
    name: string | null
    measure: string | null
    description: string
    sql: string
    measures: number
    outcome: string
    matchedMetricId: string | null
    complexity: number
    people: number
    built: number
    viewed: number
    charts: ChartSourceApi[]
    other_charts: number
    surfaces: SurfaceSourceApi[]
    agents: AgentSourceApi | null
}

export interface NewMetricPrefill {
    display_name: string
    name: string
    description: string
    sql: string
}

function proposalRow(proposal: ProposedMetricApi): ProposedRow {
    return {
        key: `proposal-${proposal.name}`,
        name: proposal.name,
        measure: null,
        description: proposal.description,
        sql: proposal.definition,
        measures: proposal.measures,
        outcome: 'uncovered',
        matchedMetricId: null,
        complexity: proposal.complexity,
        people: proposal.people,
        built: proposal.built,
        viewed: proposal.views,
        charts: proposal.charts,
        other_charts: proposal.other_charts,
        surfaces: proposal.surfaces,
        agents: proposal.agents,
    }
}

/** One row per proposal, then one per remaining measure the catalog does not cover, ranked by complexity, then people, built and views. */
export function buildProposedRows(payload: UsageSnapshotPayloadApi): ProposedRow[] {
    const proposals = payload.proposed_metrics ?? []
    const proposalNames = new Set(proposals.map((proposal) => proposal.name))
    const groups = payload.uncovered ?? []

    const rows = proposals.map(proposalRow)
    for (const group of groups) {
        if (group.draft_name && proposalNames.has(group.draft_name)) {
            continue
        }
        // The catalog already has this measure, so there is nothing to propose.
        if (group.outcome === 'covered') {
            continue
        }
        rows.push({
            key: group.fingerprint_digest,
            name: group.draft_name,
            measure: group.measure,
            description: group.draft_description ?? '',
            sql: group.draft_definition || group.sample_sql,
            measures: 1,
            outcome: group.outcome,
            matchedMetricId: group.matched_metric_id,
            complexity: group.complexity,
            people: group.distinct_people,
            built: group.built,
            viewed: group.views,
            charts: [],
            other_charts: 0,
            surfaces: [],
            agents: null,
        })
    }
    return rows
        .sort(
            (a, b) =>
                b.complexity - a.complexity ||
                b.people - a.people ||
                b.built - a.built ||
                b.viewed - a.viewed ||
                a.key.localeCompare(b.key)
        )
        .slice(0, SHOWN_ROWS)
}

export function proposedRowPrefill(row: ProposedRow): NewMetricPrefill {
    const words = (row.name ?? '').replace(/_+/g, ' ').trim()
    return {
        display_name: words ? words[0].toUpperCase() + words.slice(1) : '',
        name: row.name ?? '',
        description: row.description,
        sql: row.sql,
    }
}
