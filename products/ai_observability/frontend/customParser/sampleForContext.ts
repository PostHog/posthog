const MAX_STRING_LENGTH = 280
const MAX_ARRAY_ITEMS = 5
const MAX_TOTAL_LENGTH = 8000
const MAX_DEPTH = 8

// Renders an event payload as JSON for the Max tool context: every key survives (recipes
// match on shape) while long strings and arrays are truncated.
export function sampleForContext(value: unknown): string {
    const rendered = JSON.stringify(truncateValue(value, 0), null, 2) ?? 'null'
    if (rendered.length <= MAX_TOTAL_LENGTH) {
        return rendered
    }
    return `${rendered.slice(0, MAX_TOTAL_LENGTH)}\n… (sample truncated)`
}

function truncateValue(value: unknown, depth: number): unknown {
    if (typeof value === 'string') {
        return value.length > MAX_STRING_LENGTH ? `${value.slice(0, MAX_STRING_LENGTH)}… (truncated)` : value
    }
    if (depth >= MAX_DEPTH || value === null || typeof value !== 'object') {
        return value
    }
    if (Array.isArray(value)) {
        if (value.length <= MAX_ARRAY_ITEMS) {
            return value.map((item) => truncateValue(item, depth + 1))
        }
        // Keep head and tail: trailing items often have a different shape a recipe needs to see
        const omitted = value.length - MAX_ARRAY_ITEMS
        return [
            ...value.slice(0, MAX_ARRAY_ITEMS - 1).map((item) => truncateValue(item, depth + 1)),
            `… (${omitted} more ${omitted === 1 ? 'item' : 'items'})`,
            truncateValue(value[value.length - 1], depth + 1),
        ]
    }
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, truncateValue(child, depth + 1)]))
}
