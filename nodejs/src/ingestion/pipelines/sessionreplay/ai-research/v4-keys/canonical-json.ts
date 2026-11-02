/** Both readers rebuild this byte for byte, so key order is sorted and there is no whitespace. */
export function canonicalJson(value: unknown): string {
    if (Array.isArray(value)) {
        return `[${value.map(canonicalJson).join(',')}]`
    }
    if (value && typeof value === 'object') {
        // An absent field is left out, as in the Rust context, so `{ ref: undefined }` matches `{}`.
        return `{${Object.keys(value)
            .filter((k) => (value as Record<string, unknown>)[k] !== undefined)
            .sort()
            .map((k) => `${JSON.stringify(k)}:${canonicalJson((value as Record<string, unknown>)[k])}`)
            .join(',')}}`
    }
    return JSON.stringify(value)
}
