// Schema version this exporter targets - update when provider schema changes
export const POSTHOG_PROVIDER_VERSION = '0.4'

export interface HclExportOptions {
    /** Include import block for existing resources (default: true for saved resources) */
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
export function sanitizeResourceName(name: string, fallback: string = 'resource'): string {
    let result = name
        .toLowerCase()
        .replace(/[^a-z0-9_]/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_+|_+$/g, '')

    // Terraform resource names cannot start with a digit - prefix with underscore
    if (/^[0-9]/.test(result)) {
        result = `_${result}`
    }

    return result || fallback
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
export function formatHclValue(value: unknown): string {
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
export function formatJsonForHcl(obj: unknown, baseIndent: string = '  '): string {
    const jsonStr = JSON.stringify(obj, null, 2)
    return jsonStr
        .split('\n')
        .map((line, index) => (index === 0 ? line : baseIndent + line))
        .join('\n')
}

/**
 * Adds managed-by:terraform tag to existing tags.
 */
export function addManagedByTag(tags: unknown): string[] {
    const existingTags = Array.isArray(tags) ? tags : []
    return existingTags.includes('managed-by:terraform') ? existingTags : [...existingTags, 'managed-by:terraform']
}

// ============================================================================
// Generic Resource Exporter Framework
// ============================================================================

export interface FieldMapping<T> {
    /** Field name in the source model */
    source: keyof T | string
    /** Field name in Terraform provider schema */
    target: string
    /** Whether to include this field (receives the field value and full resource) */
    condition?: (value: unknown, resource: T) => boolean
    /** Transform the value before formatting (returns raw HCL string if provided) */
    transform?: (value: unknown) => string
    /** Add blank line before this field */
    blankLineBefore?: boolean
}

export interface ResourceExporter<T> {
    /** Terraform resource type (e.g., 'posthog_insight') */
    resourceType: string
    /** Human-readable label for comments (e.g., 'insight') */
    resourceLabel: string
    /** Field mappings from source model to Terraform schema */
    fieldMappings: FieldMapping<T>[]
    /** Validation function returning warnings */
    validate: (resource: T) => string[]
    /** Get the resource name for Terraform (used in resource block name) */
    getResourceName: (resource: T) => string
    /** Get the resource ID (for import blocks) */
    getId: (resource: T) => number | string | undefined
    /** Get optional short ID for comments */
    getShortId?: (resource: T) => string | undefined
}

/**
 * Generic HCL generator that works with any resource type.
 */
export function generateHCL<T>(
    resource: T,
    exporter: ResourceExporter<T>,
    options: HclExportOptions = {}
): HclExportResult {
    const resourceId = exporter.getId(resource)
    const { includeImport = resourceId !== undefined } = options

    const warnings = exporter.validate(resource)
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

    // Add warnings as comments
    if (warnings.length > 0) {
        lines.push(`#`)
        lines.push(`# WARNINGS:`)
        warnings.forEach((warning) => {
            lines.push(`#   - ${warning}`)
        })
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
        const shouldInclude = mapping.condition ? mapping.condition(value, resource) : value !== undefined

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
