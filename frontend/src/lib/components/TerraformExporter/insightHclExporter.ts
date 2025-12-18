import {
    addManagedByTag,
    formatHclValue,
    formatIdsWithReplacements,
    formatJsonForHcl,
    sanitizeResourceName,
} from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { AlertType } from '~/lib/components/Alerts/types'
import { HogFunctionType, InsightModel } from '~/types'

import { generateAlertHCL } from './alertHclExporter'
import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'

export interface InsightHclExportOptions extends HclExportOptions {
    /** Map of dashboard IDs to their TF references */
    dashboardIdReplacements?: Map<number, string>
    /** Child alerts to include in export */
    alerts?: AlertType[]
    /** Hog functions grouped by alert ID */
    hogFunctionsByAlertId?: Map<string, HogFunctionType[]>
}

export interface InsightExportResult extends HclExportResult {
    resourceCounts: {
        dashboards: number
        insights: number
        alerts: number
        hogFunctions: number
    }
}

/**
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/insight
 */
const INSIGHT_FIELD_MAPPINGS: FieldMapping<Partial<InsightModel>, InsightHclExportOptions>[] = [
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
        source: 'derived_name',
        target: 'derived_name',
        shouldInclude: (v, insight) => !!v && !insight.name,
    },
    {
        source: 'query',
        target: 'query_json',
        shouldInclude: (v) => !!v,
        transform: (v) => `jsonencode(${formatJsonForHcl(v)})`,
    },
    {
        source: 'tags',
        target: 'tags',
        shouldInclude: () => true, // Always include tags to add managed-by tag
        transform: (v) => formatHclValue(addManagedByTag(v)),
    },
    {
        source: '_create_in_folder',
        target: 'create_in_folder',
        shouldInclude: (v) => !!v,
    },
    {
        source: 'dashboards',
        target: 'dashboard_ids',
        shouldInclude: (v) => Array.isArray(v) && v.length > 0,
        transform: (v, _, options) => formatIdsWithReplacements(v as number[], options.dashboardIdReplacements),
    },
]

function validateInsight(insight: Partial<InsightModel>, options?: InsightHclExportOptions): string[] {
    const warnings: string[] = []

    if (!insight.query) {
        warnings.push('Missing required field: query. The insight will fail to apply without a query_json value.')
    }

    if (!insight.name && !insight.derived_name) {
        warnings.push(
            'No name or derived_name provided. Consider adding a name for better identification in Terraform state.'
        )
    }

    if (insight.dashboards && insight.dashboards.length > 0) {
        const hasUnresolvedIds = insight.dashboards.some((id) => !options?.dashboardIdReplacements?.has(id))
        if (hasUnresolvedIds) {
            warnings.push(
                'Some `dashboard_ids` are hardcoded. After exporting, consider referencing the Terraform resource instead (for example, `posthog_dashboard.my_dashboard.id`) so the dashboard is managed alongside this configuration.'
            )
        }
    }

    return warnings
}

const INSIGHT_EXPORTER: ResourceExporter<Partial<InsightModel>, InsightHclExportOptions> = {
    resourceType: 'posthog_insight',
    resourceLabel: 'insight',
    fieldMappings: INSIGHT_FIELD_MAPPINGS,
    validate: validateInsight,
    getResourceName: (i) => i.name || i.derived_name || `insight_${i.id || 'new'}`,
    getId: (i) => i.id,
    getShortId: (i) => i.short_id,
}

export function generateInsightHCL(
    insight: Partial<InsightModel>,
    options: InsightHclExportOptions = {}
): InsightExportResult {
    const allWarnings: string[] = []
    const hclSections: string[] = []

    const alertCount = options.alerts?.length || 0
    const hogFunctionCount = options.hogFunctionsByAlertId
        ? Array.from(options.hogFunctionsByAlertId.values()).flat().length
        : 0

    const result = generateHCL(insight, INSIGHT_EXPORTER, options)
    allWarnings.push(...result.warnings)
    hclSections.push(result.hcl)

    if (options.alerts && options.alerts.length > 0) {
        const insightTfName = sanitizeResourceName(
            INSIGHT_EXPORTER.getResourceName(insight),
            INSIGHT_EXPORTER.resourceLabel
        )
        const insightTfReference = `${INSIGHT_EXPORTER.resourceType}.${insightTfName}.id`

        for (const alert of options.alerts) {
            const hogFunctions = options.hogFunctionsByAlertId?.get(alert.id) || []

            const alertResult = generateAlertHCL(alert, {
                insightTfReference,
                hogFunctions,
            })
            hclSections.push('')
            hclSections.push(alertResult.hcl)
            allWarnings.push(...alertResult.warnings.map((w) => `[Alert: ${alert.name || alert.id}] ${w}`))
        }
    }

    return {
        hcl: hclSections.join('\n'),
        warnings: allWarnings,
        resourceCounts: {
            dashboards: 0,
            insights: 1,
            alerts: alertCount,
            hogFunctions: hogFunctionCount,
        },
    }
}
