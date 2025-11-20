import { InsightModel } from '~/types'

/**
 * Sanitizes a string to be used as a Terraform resource name.
 * Converts to lowercase and replaces non-alphanumeric characters with underscores.
 */
function sanitizeResourceName(name: string): string {
    return (
        name
            .toLowerCase()
            .replace(/[^a-z0-9_]/g, '_')
            .replace(/^[0-9]/, '_$&')
            .replace(/_+/g, '_')
            .replace(/^_|_$/g, '') || 'insight'
    )
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
function formatHclValue(value: any): string {
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
 * Generates Terraform HCL configuration for a PostHog insight.
 * Maps InsightModel fields to the Terraform provider schema.
 */
export function generateInsightHCL(insight: Partial<InsightModel>): string {
    const resourceName = sanitizeResourceName(
        insight.name || insight.derived_name || `insight_${insight.id || 'unknown'}`
    )

    const lines: string[] = []

    if (insight.id !== undefined) {
        lines.push(`# Generated from PostHog insight ID: ${insight.id}`)
    }
    if (insight.short_id) {
        lines.push(`# Short ID: ${insight.short_id}`)
    }
    if (insight.created_at) {
        lines.push(`# Created: ${insight.created_at}`)
    }
    if (insight.last_modified_at) {
        lines.push(`# Last modified: ${insight.last_modified_at}`)
    }

    lines.push('')
    lines.push(`import {`)
    lines.push(`  to = posthog_insight.${resourceName}`)
    lines.push(`  id = "${insight.id}"`)
    lines.push(`}`)
    lines.push('')
    lines.push(`resource "posthog_insight" "${resourceName}" {`)

    if (insight.id) {
        lines.push(`  id        = ${formatHclValue(insight.id)}`)
    }

    if (insight.name) {
        lines.push(`  name        = ${formatHclValue(insight.name)}`)
    }

    if (insight.description) {
        lines.push(`  description = ${formatHclValue(insight.description)}`)
    }

    if (insight.derived_name) {
        lines.push(`  derived_name = ${formatHclValue(insight.derived_name)}`)
    }

    if (insight.query) {
        lines.push('')
        lines.push('  query_json = jsonencode({')

        const queryStr = JSON.stringify(insight.query, null, 2)
        const queryLines = queryStr.split('\n').slice(1, -1)
        queryLines.forEach((line) => {
            lines.push(`  ${line}`)
        })

        lines.push('  })')
    }

    if (insight.tags && insight.tags.length > 0) {
        lines.push(`  tags = ${formatHclValue(insight.tags)}`)
    }

    if (insight._create_in_folder) {
        lines.push(`  create_in_folder = ${formatHclValue(insight._create_in_folder)}`)
    }

    if (insight.dashboards && insight.dashboards.length > 0) {
        lines.push(`  dashboard_ids = ${formatHclValue(insight.dashboards)}`)
    }

    lines.push('}')

    return lines.join('\n')
}
