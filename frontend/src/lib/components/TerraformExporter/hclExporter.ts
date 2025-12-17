import { formatHclValue, sanitizeResourceName } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

// Schema version this exporter targets - update when provider schema changes
export const POSTHOG_PROVIDER_VERSION = '1.0'

export interface HclExportResult {
    hcl: string
    warnings: string[]
}

export interface HclExportOptions {
    /** Include import block for existing resources (default: true for saved resources) */
    includeImport?: boolean
}

export interface ResourceExporter<T, O extends HclExportOptions = HclExportOptions> {
    /** Terraform resource type (e.g., 'posthog_insight') */
    resourceType: string
    /** Human-readable label for comments (e.g., 'insight') */
    resourceLabel: string
    /** Field mappings from source model to Terraform schema */
    fieldMappings: FieldMapping<T, O>[]
    /** Validation function returning warnings. Receives options for context-aware validation. */
    validate: (resource: T, options: O) => string[]
    /** Get the resource name for Terraform (used in resource block name) */
    getResourceName: (resource: T) => string
    /** Get the resource ID (for import blocks) */
    getId: (resource: T) => number | string | undefined
    /** Get optional short ID for comments */
    getShortId?: (resource: T) => string | undefined
}

export interface FieldMapping<T, O extends HclExportOptions = HclExportOptions> {
    /** Field name in the source model */
    source: keyof T | string
    /** Field name in Terraform provider schema */
    target: string
    /** Whether to include this field (receives the field value and full resource) */
    shouldInclude?: (value: unknown, resource: T) => boolean
    /** Transform the value. Receives resource and options for full context. */
    transform?: (value: unknown, resource: T, options: O) => string
}

export function generateHCL<T, O extends HclExportOptions = HclExportOptions>(
    resource: T,
    exporter: ResourceExporter<T, O>,
    options: O = {} as O
): HclExportResult {
    const resourceId = exporter.getId(resource)
    const { includeImport = resourceId !== undefined } = options

    const warnings = exporter.validate(resource, options)
    const resourceName = sanitizeResourceName(exporter.getResourceName(resource), exporter.resourceLabel)

    const lines: string[] = []

    // Header comment with metadata
    lines.push(`# Terraform configuration for PostHog ${exporter.resourceLabel}`)
    lines.push(`# Compatible with posthog provider v${POSTHOG_PROVIDER_VERSION}`)
    if (resourceId !== undefined) {
        lines.push(`# Source ${exporter.resourceLabel} ID: ${resourceId}`)
    }
    const shortId = exporter.getShortId?.(resource)
    if (shortId) {
        lines.push(`# Short ID: ${shortId}`)
    }

    lines.push('')

    // Import block for existing resources only
    if (includeImport && resourceId !== undefined) {
        lines.push(`import {`)
        lines.push(`  to = ${exporter.resourceType}.${resourceName}`)
        lines.push(`  id = "${resourceId}"`)
        lines.push(`}`)
        lines.push('')
    }

    // Resource block
    lines.push(`resource "${exporter.resourceType}" "${resourceName}" {`)

    // Generate fields from declarative mapping
    for (const mapping of exporter.fieldMappings) {
        const value = (resource as Record<string, unknown>)[mapping.source as string]
        const shouldInclude = mapping.shouldInclude ? mapping.shouldInclude(value, resource) : value !== undefined

        if (shouldInclude) {
            const formattedValue = mapping.transform
                ? mapping.transform(value, resource, options)
                : formatHclValue(value)
            lines.push(`  ${mapping.target} = ${formattedValue}`)
        }
    }

    lines.push('}')

    return {
        hcl: lines.join('\n'),
        warnings,
    }
}
