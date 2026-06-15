import { formatHclValue, formatJsonForHcl } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { DashboardTile, DashboardType } from '~/types'

import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'

export interface DashboardLayoutHclExportOptions extends HclExportOptions {
    /** TF reference for the dashboard_id field (e.g. "posthog_dashboard.my_dashboard.id") */
    dashboardTfReference: string
    /** Map of insight IDs to their TF references (e.g. "posthog_insight.my_insight.id") */
    insightIdReplacements: Map<number, string>
}

function formatTileObject(tile: DashboardTile<any>, insightIdReplacements: Map<number, string>): string[] {
    const lines: string[] = []
    lines.push('    {')

    if (tile.insight?.id) {
        const tfRef = insightIdReplacements.get(tile.insight.id)
        if (tfRef) {
            lines.push(`      insight_id = ${tfRef}`)
        } else {
            lines.push(`      insight_id = ${tile.insight.id}`)
        }
    }

    if (tile.text?.body) {
        lines.push(`      text_body = ${formatHclValue(tile.text.body)}`)
    }

    if (tile.color) {
        lines.push(`      color = ${formatHclValue(tile.color)}`)
    }

    if (tile.layouts && Object.keys(tile.layouts).length > 0) {
        lines.push(`      layouts_json = jsonencode(${formatJsonForHcl(tile.layouts, '      ')})`)
    }

    lines.push('    },')
    return lines
}

/**
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/dashboard_layout
 */
const DASHBOARD_LAYOUT_FIELD_MAPPINGS: FieldMapping<Partial<DashboardType<any>>, DashboardLayoutHclExportOptions>[] = [
    {
        source: 'id',
        target: 'dashboard_id',
        shouldInclude: () => true,
        transform: (_, _dashboard, options) => options.dashboardTfReference,
    },
    {
        source: 'tiles',
        target: 'tiles',
        shouldInclude: () => true,
        transform: (_, dashboard, options) => {
            const activeTiles = (dashboard.tiles || []).filter((t) => !t.deleted && (t.insight?.id || t.text?.body))
            if (activeTiles.length === 0) {
                return '[]'
            }
            const tileLines: string[] = ['[']
            for (const tile of activeTiles) {
                tileLines.push(...formatTileObject(tile, options.insightIdReplacements))
            }
            tileLines.push('  ]')
            return tileLines.join('\n')
        },
    },
]

// No validation needed: this resource is generated in a way that we
// always provide the key details.
function validateDashboardLayout(): string[] {
    return []
}

const DASHBOARD_LAYOUT_EXPORTER: ResourceExporter<Partial<DashboardType<any>>, DashboardLayoutHclExportOptions> = {
    resourceType: 'posthog_dashboard_layout',
    resourceLabel: 'dashboard_layout',
    fieldMappings: DASHBOARD_LAYOUT_FIELD_MAPPINGS,
    validate: validateDashboardLayout,
    getResourceName: (d) => d.name || `dashboard_layout_${d.id || 'new'}`,
    getId: (d) => d.id,
}

export function generateDashboardLayoutHCL(
    dashboard: Partial<DashboardType<any>>,
    options: DashboardLayoutHclExportOptions
): HclExportResult {
    return generateHCL(dashboard, DASHBOARD_LAYOUT_EXPORTER, options)
}
