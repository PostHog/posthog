export function dataLink(
    template: string,
    value: unknown,
    row: Record<string, unknown>,
    time?: { from: string; to: string }
): string | undefined {
    const text = (item: unknown): string => (item === null || item === undefined ? '' : String(item))
    const fill = (part: string, encode: (raw: string) => string): string =>
        part
            .replace(/\$\{__value(?:\.(?:raw|text|numeric))?(?::[\w:]+)?\}/g, () => encode(text(value)))
            .replace(/\$\{__data\.fields(?:\.([\w.$-]+)|\["([^"]+)"\])(?::[\w:]+)?\}/g, (_, plain, quoted) =>
                encode(text(row[plain ?? quoted]))
            )
            .replace(/\$\{?__url_time_range\}?/g, () =>
                time ? `from=${encodeURIComponent(time.from)}&to=${encodeURIComponent(time.to)}` : ''
            )
            .replace(/\$\{__from(?::[^}]*)?\}|\$__from\b/g, () => (time ? encodeURIComponent(time.from) : ''))
            .replace(/\$\{__to(?::[^}]*)?\}|\$__to\b/g, () => (time ? encodeURIComponent(time.to) : ''))
    const queryStart = template.search(/[?#]/)
    const url = (
        queryStart < 0
            ? fill(template, (raw) => raw)
            : fill(template.slice(0, queryStart), (raw) => raw) + fill(template.slice(queryStart), encodeURIComponent)
    ).trim()
    return /^(https?:\/\/|\/(?!\/))/i.test(url) ? url : undefined
}
