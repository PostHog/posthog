import { InsightModel } from '~/types'

import {
    FieldMapping,
    HclExportOptions,
    HclExportResult,
    ResourceExporter,
    addManagedByTag,
    formatHclValue,
    formatJsonForHcl,
    generateHCL,
} from './hclExporter'

// ============================================================================
// Insight Exporter
// ============================================================================

const INSIGHT_FIELD_MAPPINGS: FieldMapping<Partial<InsightModel>>[] = [
    {
        source: 'name',
        target: 'name',
        condition: (v) => !!v,
    },
    {
        source: 'description',
        target: 'description',
        condition: (v) => !!v,
    },
    {
        source: 'derived_name',
        target: 'derived_name',
        condition: (v, insight) => !!v && !insight.name,
    },
    {
        source: 'query',
        target: 'query_json',
        condition: (v) => !!v,
        transform: (v) => `jsonencode(${formatJsonForHcl(v)})`,
        blankLineBefore: true,
    },
    {
        source: 'tags',
        target: 'tags',
        condition: () => true, // Always include tags to add managed-by tag
        transform: (v) => formatHclValue(addManagedByTag(v)),
        blankLineBefore: true,
    },
    {
        source: '_create_in_folder',
        target: 'create_in_folder',
        condition: (v) => !!v,
    },
    {
        source: 'dashboards',
        target: 'dashboard_ids',
        condition: (v) => Array.isArray(v) && v.length > 0,
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
            'dashboard_ids are hardcoded. Consider using Terraform references instead (e.g., posthog_dashboard.my_dashboard.id) to ensure dashboards exist and are managed together.'
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

/**
 * Generates Terraform HCL configuration for a PostHog insight.
 * Maps InsightModel fields to the Terraform provider schema.
 *
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/insight
 */
export function generateInsightHCL(insight: Partial<InsightModel>, options: HclExportOptions = {}): string {
    return generateHCL(insight, INSIGHT_EXPORTER, options).hcl
}

/**
 * Generates Terraform HCL configuration with validation warnings.
 * Use this when you want to display warnings to the user.
 */
export function generateInsightHCLWithWarnings(
    insight: Partial<InsightModel>,
    options: HclExportOptions = {}
): HclExportResult {
    return generateHCL(insight, INSIGHT_EXPORTER, options)
}
