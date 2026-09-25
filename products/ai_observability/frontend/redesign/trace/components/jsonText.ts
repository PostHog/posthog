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
