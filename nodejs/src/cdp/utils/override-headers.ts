export function overrideHeaders(
    headers: Record<string, string>,
    overrides: Record<string, string>
): Record<string, string> {
    const overriddenNames = new Set(Object.keys(overrides).map((name) => name.toLowerCase()))

    const merged: Record<string, string> = {}
    for (const [name, value] of Object.entries(headers)) {
        if (!overriddenNames.has(name.toLowerCase())) {
            merged[name] = value
        }
    }

    return { ...merged, ...overrides }
}
