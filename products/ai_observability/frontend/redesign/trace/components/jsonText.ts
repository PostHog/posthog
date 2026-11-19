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
        // Pushed one by one: spreading a large array into one call exceeds the engine's argument limit.
        if (Array.isArray(item)) {
            for (let index = item.length - 1; index >= 0; index--) {
                pending.push(item[index])
            }
        } else if (isPlainObject(item)) {
            const entries = Object.entries(item)
            for (let index = entries.length - 1; index >= 0; index--) {
                pending.push(entries[index][1], entries[index][0])
            }
        } else {
            parts.push(String(item))
        }
    }
    return parts.join('\n')
}
