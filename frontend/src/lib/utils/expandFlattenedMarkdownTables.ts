const TABLE_DELIMITER_SEGMENT_RE = /^\|(?:\s*:?-{2,}:?\s*\|)+\s*$/
const FLATTENED_TABLE_ROW_BOUNDARY_RE = /(?<=\|)\s+(?=\|)/

// Slack, ChatGPT, Notion etc. strip newlines between table rows on plain-text copy.
// Only splits when a delimiter row (`|---|---|`) is present, so prose with `|` is safe.
export function expandFlattenedMarkdownTables(text: string): string {
    return text
        .split('\n')
        .flatMap((line) => {
            const segments = line.split(FLATTENED_TABLE_ROW_BOUNDARY_RE).map((s) => s.trim())
            if (segments.length < 2 || !segments.some((s) => TABLE_DELIMITER_SEGMENT_RE.test(s))) {
                return [line]
            }
            return segments
        })
        .join('\n')
}
