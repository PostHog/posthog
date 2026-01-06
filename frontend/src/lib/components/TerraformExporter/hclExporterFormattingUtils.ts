const MANAGED_BY_TAG = 'managed-by:terraform'

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

function escapeHclString(str: string): string {
    return str
        .replace(/\\/g, '\\\\')
        .replace(/"/g, '\\"')
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r')
        .replace(/\t/g, '\\t')
}

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

export function formatJsonForHcl(obj: unknown, baseIndent: string = '  '): string {
    const jsonStr = JSON.stringify(obj, null, 2)
    return jsonStr
        .split('\n')
        .map((line, index) => (index === 0 ? line : baseIndent + line))
        .join('\n')
}

export function addManagedByTag(tags: unknown): string[] {
    const existingTags = Array.isArray(tags) ? tags : []
    return existingTags.includes(MANAGED_BY_TAG) ? existingTags : [...existingTags, MANAGED_BY_TAG]
}

/**
 * Format an array of IDs, replacing any that have TF references.
 */
export function formatIdsWithReplacements(
    ids: (string | number)[],
    replacements?: Map<string | number, string>
): string {
    if (!replacements?.size) {
        return formatHclValue(ids)
    }
    const parts = ids.map((id) => replacements.get(id) ?? formatHclValue(id))
    return `[${parts.join(', ')}]`
}
