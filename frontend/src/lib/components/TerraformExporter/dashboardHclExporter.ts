import {
    addManagedByTag,
    formatHclValue,
    sanitizeResourceName,
} from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { AlertType } from '~/lib/components/Alerts/types'
import { DashboardBasicType, HogFunctionType, InsightModel } from '~/types'

import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'
import { generateInsightHCL } from './insightHclExporter'

export interface DashboardHclExportOptions extends HclExportOptions {
    /** Child insights to include in export */
    insights?: InsightModel[]
    /** Alerts grouped by insight ID */
    alertsByInsightId?: Map<number, AlertType[]>
    /** Hog functions grouped by alert ID */
    hogFunctionsByAlertId?: Map<string, HogFunctionType[]>
}

/**
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/dashboard
 */
const DASHBOARD_FIELD_MAPPINGS: FieldMapping<Partial<DashboardBasicType>>[] = [
    {
        source: 'name',
        target: 'name',
        shouldInclude: (v) => !!v,
    },
    {
        source: 'description',
        target: 'description',
        shouldInclude: (v) => !!v,
    },
    {
        source: 'pinned',
        target: 'pinned',
        shouldInclude: (v) => v !== undefined,
    },
    {
        source: 'tags',
        target: 'tags',
        shouldInclude: () => true, // Always include tags to add managed-by tag
        transform: (v) => formatHclValue(addManagedByTag(v)),
    },
]

function validateDashboard(dashboard: Partial<DashboardBasicType>): string[] {
    const warnings: string[] = []

    if (!dashboard.name) {
        warnings.push('No name provided. Consider adding a name for better identification in Terraform state.')
    }

    return warnings
}

const DASHBOARD_EXPORTER: ResourceExporter<Partial<DashboardBasicType>> = {
    resourceType: 'posthog_dashboard',
    resourceLabel: 'dashboard',
    fieldMappings: DASHBOARD_FIELD_MAPPINGS,
    validate: validateDashboard,
    getResourceName: (d) => d.name || `dashboard_${d.id || 'new'}`,
    getId: (d) => d.id,
}

export interface DashboardExportResult extends HclExportResult {
    resourceCounts: {
        dashboards: number
        insights: number
        alerts: number
        hogFunctions: number
    }
}

export function generateDashboardHCL(
    dashboard: Partial<DashboardBasicType>,
    options: DashboardHclExportOptions = {}
): DashboardExportResult {
    const allWarnings: string[] = []
    const hclSections: string[] = []

    // Count resources for summary
    const insightCount = options.insights?.length || 0
    const alertCount = options.alertsByInsightId ? Array.from(options.alertsByInsightId.values()).flat().length : 0
    const hogFunctionCount = options.hogFunctionsByAlertId
        ? Array.from(options.hogFunctionsByAlertId.values()).flat().length
        : 0

    // Generate dashboard HCL
    const result = generateHCL(dashboard, DASHBOARD_EXPORTER, options)
    hclSections.push(result.hcl)
    allWarnings.push(...result.warnings)

    // Generate child insights if provided
    if (options.insights && options.insights.length > 0) {
        const dashboardTfName = sanitizeResourceName(
            DASHBOARD_EXPORTER.getResourceName(dashboard),
            DASHBOARD_EXPORTER.resourceLabel
        )
        const dashboardTfReference = `${DASHBOARD_EXPORTER}.${dashboardTfName}.id`

        for (const insight of options.insights) {
            const alerts = insight.id ? options.alertsByInsightId?.get(insight.id) || [] : []

            // Clear the insight's dashboards to avoid hardcoded IDs warning
            const insightWithoutDashboards: Partial<InsightModel> = {
                ...insight,
                dashboards: undefined,
            }

            const insightResult = generateInsightHCL(insightWithoutDashboards, {
                dashboardTfReferences: [dashboardTfReference],
                alerts,
                hogFunctionsByAlertId: options.hogFunctionsByAlertId,
            })
            hclSections.push('')
            hclSections.push(insightResult.hcl)
            allWarnings.push(...insightResult.warnings.map((w) => `[Insight: ${insight.name || insight.id}] ${w}`))
        }
    }

    return {
        hcl: hclSections.join('\n'),
        warnings: allWarnings,
        resourceCounts: {
            dashboards: 1,
            insights: insightCount,
            alerts: alertCount,
            hogFunctions: hogFunctionCount,
        },
    }
}
