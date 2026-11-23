// The text of an indented template written like an HCL `<<-` heredoc: the smallest indentation of
// the template's own lines comes off every one of them, interpolated text is left as it is, and the
// text ends with one line break. The queries in PostHog were written this way, so matching it keeps
// them byte for byte.
export function heredoc(strings: TemplateStringsArray, ...values: unknown[]): string {
    const parts = [...strings]
    parts[0] = (parts[0] ?? '').replace(/^\n/, '')
    const last = parts.length - 1
    parts[last] = (parts[last] ?? '').replace(/\n[ \t]*$/, '\n')
    // A line starts at the beginning of the text or after a line break in a literal part. It counts
    // toward the indentation unless it is blank to its end.
    const starts: { part: number; offset: number; blank: boolean }[] = []
    parts.forEach((part, index) => {
        let offset = index === 0 ? 0 : part.indexOf('\n') + 1
        if (index !== 0 && offset === 0) {
            return
        }
        while (offset <= part.length) {
            const end = part.indexOf('\n', offset)
            const line = end === -1 ? part.slice(offset) : part.slice(offset, end)
            const followedByValue = end === -1 && index < last
            if (!(end === -1 && index === last && line === '')) {
                starts.push({ part: index, offset, blank: line.trim() === '' && !followedByValue })
            }
            if (end === -1) {
                break
            }
            offset = end + 1
        }
    })
    const indentOf = ({ part, offset }: { part: number; offset: number }): number => {
        const rest = (parts[part] ?? '').slice(offset)
        return rest.length - rest.replace(/^[ \t]*/, '').length
    }
    const indent = Math.min(...starts.filter((start) => !start.blank).map(indentOf))
    const trimmed = parts.map((part, index) => {
        const here = starts.filter((start) => start.part === index).sort((a, b) => b.offset - a.offset)
        let text = part
        for (const start of here) {
            const strip = Math.min(indent, indentOf(start))
            text = text.slice(0, start.offset) + text.slice(start.offset + strip)
        }
        return text
    })
    return trimmed.reduce((text, part, index) => text + part + (index < values.length ? String(values[index]) : ''), '')
}
