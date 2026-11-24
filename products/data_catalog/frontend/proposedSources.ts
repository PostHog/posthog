import { pluralize } from 'lib/utils/strings'

import type { SurfaceSourceApi } from './generated/api.schemas'
import type { ProposedRow } from './proposedRows'

type ProposedUsage = Pick<
    ProposedRow,
    'people' | 'built' | 'viewed' | 'charts' | 'other_charts' | 'surfaces' | 'agents'
>

const SURFACE_NAMES: Record<string, string> = {
    product_analytics: 'product analytics',
    sql_editor: 'SQL editor',
    notebooks: 'notebooks',
    canvas: 'canvases',
    warehouse: 'data warehouse',
    today: 'Today page',
}
const FALLBACK_SURFACE_NAME = 'web app'
const NAMES_WITH_ARTICLE = new Set(['sql_editor', 'warehouse', 'today'])

const WRITTEN_SURFACES = new Set(['sql_editor', 'warehouse'])

function surfaceName(surface: SurfaceSourceApi): string {
    return SURFACE_NAMES[surface.product] ?? FALLBACK_SURFACE_NAME
}

/** Where a proposed metric's query was written or seen, such as "Written in the SQL editor". */
export function surfaceSourceLabel(surface: SurfaceSourceApi): string {
    const verb = WRITTEN_SURFACES.has(surface.product) ? 'Written in' : 'Viewed in'
    const article = !(surface.product in SURFACE_NAMES) || NAMES_WITH_ARTICLE.has(surface.product) ? 'the ' : ''
    return `${verb} ${article}${surfaceName(surface)}`
}

export function surfaceSourceUsage(surface: SurfaceSourceApi): string {
    return `${pluralize(surface.people, 'person', 'people')}, ${pluralize(surface.runs, 'run')}`
}

export function hasSources(usage: ProposedUsage): boolean {
    return usage.charts.length > 0 || usage.other_charts > 0 || usage.surfaces.length > 0 || usage.agents !== null
}

export function proposedUsageSummary(usage: ProposedUsage): string {
    const parts = [pluralize(usage.people, 'person', 'people')]
    if (!hasSources(usage)) {
        // A measure without a proposal has no sources, so the count of builds is the only sign of use.
        parts.push(`used ${pluralize(usage.built, 'time')}`)
        return parts.join(' · ')
    }
    const dashboards = new Set(
        usage.charts.flatMap((chart) => (chart.dashboard_id === null ? [] : [chart.dashboard_id]))
    )
    const charts = new Set(usage.charts.map((chart) => chart.insight_short_id)).size + usage.other_charts
    if (dashboards.size > 0) {
        parts.push(pluralize(dashboards.size, 'dashboard'))
    }
    if (charts > 0) {
        parts.push(pluralize(charts, 'chart'))
    }
    if (usage.agents) {
        parts.push(pluralize(usage.agents.sessions, 'agent session'))
    }
    if (usage.surfaces.length > 0) {
        parts.push(usage.surfaces.map(surfaceName).join(', '))
    }
    return parts.join(' · ')
}

export function proposedUsageTotals(usage: ProposedUsage): string {
    return `Built ${pluralize(usage.built, 'time')} by ${pluralize(usage.people, 'person', 'people')}. Viewed ${pluralize(usage.viewed, 'time')}.`
}
