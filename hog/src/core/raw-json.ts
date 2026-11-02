// Parses JSON and keeps integers beyond JavaScript's safe range as their source text, so a
// ClickHouse UInt64 survives the round trip to output unchanged, as it does in posthog-cli.
export function parseLossless(text: string): unknown {
    return JSON.parse(text, (_key, value, context) =>
        typeof value === 'number' && !Number.isSafeInteger(value) && context.source && /^-?\d+$/.test(context.source)
            ? JSON.rawJSON(context.source)
            : value
    )
}
