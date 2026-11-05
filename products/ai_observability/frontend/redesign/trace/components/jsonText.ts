export function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function toDisplayText(value: unknown): string {
    if (typeof value === 'string') {
        return value
    }
    try {
        return JSON.stringify(value, null, 2) ?? String(value)
    } catch {
        return String(value)
    }
}

/** The keys and values of a JSON value as a person reads them, with strings unescaped, for matching search text. */
export function searchableText(value: unknown): string {
    if (Array.isArray(value)) {
        return value.map(searchableText).join('\n')
    }
    if (isPlainObject(value)) {
        return Object.entries(value)
            .map(([key, entry]) => `${key}\n${searchableText(entry)}`)
            .join('\n')
    }
    return String(value)
}
