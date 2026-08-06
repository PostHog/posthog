/**
 * Human-facing label for one comma-separated segment: `#name` after the first `|`, or the
 * whole value when there is no pipe (e.g. raw id before resolution).
 */
export function getSlackChannelDisplayLabelFromTargetValueSegment(segment: string): string | null {
    const trimmed = segment.trim()
    if (!trimmed) {
        return null
    }
    const pipe = trimmed.indexOf('|')
    return pipe !== -1 ? trimmed.slice(pipe + 1).trim() : trimmed
}

export function parseCommaSeparatedSlackTargetDisplayLabels(targetValue: string): string[] {
    return targetValue
        .split(',')
        .map((part) => getSlackChannelDisplayLabelFromTargetValueSegment(part))
        .filter((x): x is string => Boolean(x))
}
