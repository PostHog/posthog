import { formatJsonForHcl, sanitizeResourceName } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { DashboardTile, DashboardType } from '~/types'

import { HclExportOptions, HclExportResult, POSTHOG_PROVIDER_VERSION } from './hclExporter'

const RESOURCE_TYPE = 'posthog_dashboard_layout'
const RESOURCE_LABEL = 'dashboard layout'

export interface DashboardLayoutHclExportOptions extends HclExportOptions {
    /** TF reference for the dashboard_id field (e.g. "posthog_dashboard.my_dashboard.id") */
    dashboardTfReference?: string
    /** Map of insight IDs to their TF references (e.g. "posthog_insight.my_insight.id") */
    insightIdReplacements?: Map<number, string>
}

function generateTileBlock(tile: DashboardTile, insightIdReplacements?: Map<number, string>): string[] {
    const lines: string[] = []
    lines.push('  tiles {')

    if (tile.insight?.id) {
        const tfRef = insightIdReplacements?.get(tile.insight.id)
        if (tfRef) {
            lines.push(`    insight_id = ${tfRef}`)
        } else {
            lines.push(`    insight_id = ${tile.insight.id}`)
        }
    }

    if (tile.text?.body) {
        lines.push(
            `    text_body = "${tile.text.body.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n')}"`
        )
    }

    if (tile.color) {
        lines.push(`    color = "${tile.color}"`)
    }

    if (tile.layouts && Object.keys(tile.layouts).length > 0) {
        lines.push(`    layouts_json = jsonencode(${formatJsonForHcl(tile.layouts, '    ')})`)
    }

    lines.push('  }')
    return lines
}

export function generateDashboardLayoutHCL(
    dashboard: Partial<DashboardType>,
    options: DashboardLayoutHclExportOptions = {}
): HclExportResult {
    const warnings: string[] = []
    const dashboardId = dashboard.id
    const { includeImport = dashboardId !== undefined } = options

    const resourceName = sanitizeResourceName(dashboard.name || `dashboard_${dashboardId || 'new'}`, 'dashboard_layout')

    const activeTiles = (dashboard.tiles || []).filter((tile) => !tile.deleted)

    const lines: string[] = []

    lines.push(`# Terraform configuration for PostHog ${RESOURCE_LABEL}`)
    lines.push(`# Compatible with posthog provider v${POSTHOG_PROVIDER_VERSION}`)
    if (dashboardId !== undefined) {
        lines.push(`# Source dashboard ID: ${dashboardId}`)
    }
    lines.push('')

    if (includeImport && dashboardId !== undefined) {
        const importId = options.projectId ? `${options.projectId}/${dashboardId}` : String(dashboardId)
        lines.push('import {')
        lines.push(`  to = ${RESOURCE_TYPE}.${resourceName}`)
        lines.push(`  id = "${importId}"`)
        lines.push('}')
        lines.push('')
    }

    lines.push(`resource "${RESOURCE_TYPE}" "${resourceName}" {`)

    if (options.dashboardTfReference) {
        lines.push(`  dashboard_id = ${options.dashboardTfReference}`)
    } else if (dashboardId !== undefined) {
        lines.push(`  dashboard_id = ${dashboardId}`)
        warnings.push(
            '`dashboard_id` is hardcoded. Consider referencing the Terraform resource instead (for example, `posthog_dashboard.my_dashboard.id`) so the dashboard is managed alongside this configuration.'
        )
    }

    for (const tile of activeTiles) {
        lines.push('')
        lines.push(...generateTileBlock(tile, options.insightIdReplacements))
    }

    lines.push('}')

    return {
        hcl: lines.join('\n'),
        warnings,
    }
}
