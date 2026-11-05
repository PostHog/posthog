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
    // An explicit stack, because a captured tool result can nest deeper than the call stack allows.
    const parts: string[] = []
    const pending: unknown[] = [value]
    while (pending.length > 0) {
        const item = pending.pop()
        if (Array.isArray(item)) {
            pending.push(...[...item].reverse())
        } else if (isPlainObject(item)) {
            for (const [key, entry] of Object.entries(item).reverse()) {
                pending.push(entry, key)
            }
        } else {
            parts.push(String(item))
        }
    }
    return parts.join('\n')
}
