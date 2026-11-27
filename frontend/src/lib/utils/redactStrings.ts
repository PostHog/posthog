/** Every string at any depth, such as `$current_url`, an autocaptured `href`, or a request in a replay snapshot.
 * A value with nothing to redact is returned as it is, so a large snapshot is not copied. */
export function redactStrings<T>(value: T, redact: (text: string) => string, seen?: WeakSet<object>): T
export function redactStrings(value: unknown, redact: (text: string) => string, seen = new WeakSet<object>()): unknown {
    if (typeof value === 'string') {
        return redact(value)
    }
    if (!value || typeof value !== 'object' || seen.has(value)) {
        return value
    }
    seen.add(value)
    if (Array.isArray(value)) {
        let copy: unknown[] | null = null
        value.forEach((item, index) => {
            const redacted = redactStrings(item, redact, seen)
            if (redacted !== item) {
                copy ??= [...value]
                copy[index] = redacted
            }
        })
        return copy ?? value
    }
    let copy: Record<string, unknown> | null = null
    for (const [key, item] of Object.entries(value)) {
        const redacted = redactStrings(item, redact, seen)
        if (redacted !== item) {
            copy ??= { ...value }
            copy[key] = redacted
        }
    }
    return copy ?? value
}
