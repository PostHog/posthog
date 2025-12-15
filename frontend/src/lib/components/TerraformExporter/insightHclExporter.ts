import {
    addManagedByTag,
    formatHclValue,
    formatJsonForHcl,
} from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { InsightModel } from '~/types'

import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'

/**
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/insight
 */
const INSIGHT_FIELD_MAPPINGS: FieldMapping<Partial<InsightModel>>[] = [
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
    },
]

function validateInsight(insight: Partial<InsightModel>): string[] {
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
        warnings.push(
            '`dashboard_ids` are hardcoded. After exporting, consider referencing the Terraform resource instead (for example, `posthog_dashboard.my_dashboard.id`) so the dashboard is managed alongside this configuration.'
        )
    }

    return warnings
}

const INSIGHT_EXPORTER: ResourceExporter<Partial<InsightModel>> = {
    resourceType: 'posthog_insight',
    resourceLabel: 'insight',
    fieldMappings: INSIGHT_FIELD_MAPPINGS,
    validate: validateInsight,
    getResourceName: (i) => i.name || i.derived_name || `insight_${i.id || 'new'}`,
    getId: (i) => i.id,
    getShortId: (i) => i.short_id,
}

export function generateInsightHCL(insight: Partial<InsightModel>, options: HclExportOptions = {}): HclExportResult {
    return generateHCL(insight, INSIGHT_EXPORTER, options)
}
