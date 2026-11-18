import { pluralize } from 'lib/utils/strings'

import type { SurfaceSourceApi } from './generated/api.schemas'

const SURFACE_LABELS: Record<string, string> = {
    product_analytics: 'product analytics',
    sql_editor: 'the SQL editor',
    notebooks: 'notebooks',
    canvas: 'canvases',
    warehouse: 'the data warehouse',
    today: 'the Today page',
}

const WRITTEN_SURFACES = new Set(['sql_editor', 'warehouse'])

/** Where a proposed metric's query was written or seen, such as "Written in the SQL editor". */
export function surfaceSourceLabel(surface: SurfaceSourceApi): string {
    const verb = WRITTEN_SURFACES.has(surface.product) ? 'Written in' : 'Viewed in'
    return `${verb} ${SURFACE_LABELS[surface.product] ?? 'the web app'}`
}

export function surfaceSourceUsage(surface: SurfaceSourceApi): string {
    return `${pluralize(surface.people, 'person', 'people')}, ${pluralize(surface.runs, 'run')}`
}
