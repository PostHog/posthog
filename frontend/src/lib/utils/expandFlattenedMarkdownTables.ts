// Matches a GFM table delimiter row like `|---|---|` or `| :---: | ---: |`. Anchored to a
// trimmed segment so we can test individual pipe-segments after splitting a flattened line.
const TABLE_DELIMITER_SEGMENT_RE = /^\|(?:\s*:?-{2,}:?\s*\|)+\s*$/

// Splits at whitespace that sits directly between two `|` characters — i.e. the boundary
// between two glued-together table rows. Inner cell separators (`| cell |`) are unaffected
// because the lookbehind requires a `|` to the immediate left of the whitespace.
const FLATTENED_TABLE_ROW_BOUNDARY_RE = /(?<=\|)\s+(?=\|)/g

/**
 * Re-expands markdown tables whose rows have been collapsed onto a single line.
 *
 * Sources like Slack, ChatGPT, and rich-text editors frequently strip the newlines
 * between table rows when copying as plain text, producing lines like:
 *
 *   `| a | b | |---|---| | 1 | 2 |`
 *
 * which `markdown-it` cannot parse as a table. This walks each line, and if it finds
 * 3+ pipe-segments separated by whitespace AND at least one segment is a delimiter row
 * (`|---|---|`), splits the line back into one row per segment. The delimiter guard makes
 * this safe against incidental `|`-containing prose.
 */
export function expandFlattenedMarkdownTables(text: string): string {
    return text
        .split('\n')
        .flatMap((line) => {
            const segments = line.split(FLATTENED_TABLE_ROW_BOUNDARY_RE).map((s) => s.trim())
            if (segments.length < 3) {
                return [line]
            }
            if (!segments.some((s) => TABLE_DELIMITER_SEGMENT_RE.test(s))) {
                return [line]
            }
            return segments
        })
        .join('\n')
}
