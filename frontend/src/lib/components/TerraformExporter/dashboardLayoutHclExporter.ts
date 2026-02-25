import { formatJsonForHcl } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { DashboardTile, DashboardType } from '~/types'

import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'

export interface DashboardLayoutHclExportOptions extends HclExportOptions {
    /** TF reference for the dashboard_id field (e.g. "posthog_dashboard.my_dashboard.id") */
    dashboardTfReference?: string
    /** Map of insight IDs to their TF references (e.g. "posthog_insight.my_insight.id") */
    insightIdReplacements?: Map<number, string>
}

function formatTileObject(tile: DashboardTile, insightIdReplacements?: Map<number, string>): string[] {
    const lines: string[] = []
    lines.push('    {')

    if (tile.insight?.id) {
        const tfRef = insightIdReplacements?.get(tile.insight.id)
        if (tfRef) {
            lines.push(`      insight_id = ${tfRef}`)
        } else {
            lines.push(`      insight_id = ${tile.insight.id}`)
        }
    }

    if (tile.text?.body) {
        lines.push(
            `      text_body = "${tile.text.body.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n')}"`
        )
    }

    if (tile.color) {
        lines.push(`      color = "${tile.color}"`)
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
const DASHBOARD_LAYOUT_FIELD_MAPPINGS: FieldMapping<Partial<DashboardType>, DashboardLayoutHclExportOptions>[] = [
    {
        source: 'id',
        target: 'dashboard_id',
        shouldInclude: (v) => v !== undefined,
        transform: (_, dashboard, options) => {
            if (options.dashboardTfReference) {
                return options.dashboardTfReference
            }
            return String(dashboard.id)
        },
    },
    {
        source: 'tiles',
        target: 'tiles',
        shouldInclude: (_, dashboard) => {
            const activeTiles = (dashboard.tiles || []).filter((t) => !t.deleted)
            return activeTiles.length > 0
        },
        transform: (_, dashboard, options) => {
            const activeTiles = (dashboard.tiles || []).filter((t) => !t.deleted)
            const tileLines: string[] = ['[']
            for (const tile of activeTiles) {
                tileLines.push(...formatTileObject(tile, options.insightIdReplacements))
            }
            tileLines.push('  ]')
            return tileLines.join('\n')
        },
    },
]

function validateDashboardLayout(
    dashboard: Partial<DashboardType>,
    options: DashboardLayoutHclExportOptions
): string[] {
    const warnings: string[] = []
    if (!options.dashboardTfReference && dashboard.id !== undefined) {
        warnings.push(
            '`dashboard_id` is hardcoded. Consider referencing the Terraform resource instead (for example, `posthog_dashboard.my_dashboard.id`) so the dashboard is managed alongside this configuration.'
        )
    }
    return warnings
}

const DASHBOARD_LAYOUT_EXPORTER: ResourceExporter<Partial<DashboardType>, DashboardLayoutHclExportOptions> = {
    resourceType: 'posthog_dashboard_layout',
    resourceLabel: 'dashboard layout',
    fieldMappings: DASHBOARD_LAYOUT_FIELD_MAPPINGS,
    validate: validateDashboardLayout,
    getResourceName: (d) => d.name || `dashboard_${d.id || 'new'}`,
    getId: (d) => d.id,
}

export function generateDashboardLayoutHCL(
    dashboard: Partial<DashboardType>,
    options: DashboardLayoutHclExportOptions = {}
): HclExportResult {
    return generateHCL(dashboard, DASHBOARD_LAYOUT_EXPORTER, options)
}
