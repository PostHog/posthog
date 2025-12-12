import { InsightModel } from '~/types'

// Schema version this exporter targets - update when provider schema changes
const POSTHOG_PROVIDER_VERSION = '0.4'

export interface HclExportOptions {
    /** Include import block for existing insights (default: true for saved insights) */
    includeImport?: boolean
}

export interface HclExportResult {
    hcl: string
    warnings: string[]
}

/**
 * Sanitizes a string to be used as a Terraform resource name.
 * Terraform resource names must start with a letter or underscore, and can only
 * contain letters, digits, and underscores.
 */
function sanitizeResourceName(name: string): string {
    let result = name
        .toLowerCase()
        .replace(/[^a-z0-9_]/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_+|_+$/g, '')

    // Terraform resource names cannot start with a digit - prefix with underscore
    if (/^[0-9]/.test(result)) {
        result = `_${result}`
    }

    return result || 'insight'
}

/**
 * Escapes special characters in strings for HCL.
 */
function escapeHclString(str: string): string {
    return str
        .replace(/\\/g, '\\\\')
        .replace(/"/g, '\\"')
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r')
        .replace(/\t/g, '\\t')
}

/**
 * Formats a value for HCL output.
 */
function formatHclValue(value: unknown): string {
    if (value === null || value === undefined) {
        return 'null'
    }

    if (typeof value === 'string') {
        return `"${escapeHclString(value)}"`
    }

    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
    }

    if (Array.isArray(value)) {
        if (value.length === 0) {
            return '[]'
        }
        const items = value.map((item) => formatHclValue(item)).join(', ')
        return `[${items}]`
    }

    return JSON.stringify(value)
}

/**
 * Formats a JSON object with proper HCL indentation.
 */
function formatJsonForHcl(obj: unknown, baseIndent: string = '  '): string {
    const jsonStr = JSON.stringify(obj, null, 2)
    return jsonStr
        .split('\n')
        .map((line, index) => (index === 0 ? line : baseIndent + line))
        .join('\n')
}

interface FieldMapping {
    /** Field name in InsightModel */
    source: keyof InsightModel | '_create_in_folder'
    /** Field name in Terraform provider schema */
    target: string
    /** Whether to include this field (receives the field value and full insight) */
    condition?: (value: unknown, insight: Partial<InsightModel>) => boolean
    /** Transform the value before formatting (returns raw HCL string if provided) */
    transform?: (value: unknown) => string
    /** Add blank line before this field */
    blankLineBefore?: boolean
}

/**
 * Declarative mapping from InsightModel fields to Terraform provider schema.
 * Add new fields here when the provider schema changes.
 */
const FIELD_MAPPINGS: FieldMapping[] = [
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
        transform: (v) => {
            const existingTags = Array.isArray(v) ? v : []
            const tagsWithManagedBy = existingTags.includes('managed-by:terraform')
                ? existingTags
                : [...existingTags, 'managed-by:terraform']
            return formatHclValue(tagsWithManagedBy)
        },
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

/**
 * Validates the insight and returns any warnings.
 */
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

/**
 * Generates Terraform HCL configuration for a PostHog insight.
 * Maps InsightModel fields to the Terraform provider schema.
 *
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/insight
 */
export function generateInsightHCL(insight: Partial<InsightModel>, options: HclExportOptions = {}): string {
    const result = generateInsightHCLWithWarnings(insight, options)
    return result.hcl
}

/**
 * Generates Terraform HCL configuration with validation warnings.
 * Use this when you want to display warnings to the user.
 */
export function generateInsightHCLWithWarnings(
    insight: Partial<InsightModel>,
    options: HclExportOptions = {}
): HclExportResult {
    const { includeImport = insight.id !== undefined } = options

    const warnings = validateInsight(insight)
    const resourceName = sanitizeResourceName(insight.name || insight.derived_name || `insight_${insight.id || 'new'}`)

    const lines: string[] = []

    // Header comment with metadata
    lines.push(`# Terraform configuration for PostHog insight`)
    lines.push(`# Compatible with posthog provider v${POSTHOG_PROVIDER_VERSION}`)
    if (insight.id !== undefined) {
        lines.push(`# Source insight ID: ${insight.id}`)
    }
    if (insight.short_id) {
        lines.push(`# Short ID: ${insight.short_id}`)
    }

    // Add warnings as comments
    if (warnings.length > 0) {
        lines.push(`#`)
        lines.push(`# WARNINGS:`)
        warnings.forEach((warning) => {
            lines.push(`#   - ${warning}`)
        })
    }

    lines.push('')

    // Import block for existing insights only
    if (includeImport && insight.id !== undefined) {
        lines.push(`import {`)
        lines.push(`  to = posthog_insight.${resourceName}`)
        lines.push(`  id = "${insight.id}"`)
        lines.push(`}`)
        lines.push('')
    }

    // Resource block
    lines.push(`resource "posthog_insight" "${resourceName}" {`)

    // Generate fields from declarative mapping
    for (const mapping of FIELD_MAPPINGS) {
        const value = insight[mapping.source as keyof typeof insight]
        const shouldInclude = mapping.condition ? mapping.condition(value, insight) : value !== undefined

        if (shouldInclude) {
            if (mapping.blankLineBefore) {
                lines.push('')
            }
            const formattedValue = mapping.transform ? mapping.transform(value) : formatHclValue(value)
            lines.push(`  ${mapping.target} = ${formattedValue}`)
        }
    }

    lines.push('}')

    return {
        hcl: lines.join('\n'),
        warnings,
    }
}
