/**
 * Slack destinations in PostHog use `channelId|#channel-name` (see SlackIntegrationHelpers
 * option keys). Some stored values are channel id only until channels are loaded.
 */

export function getSlackChannelIdFromTargetValue(value: string): string {
    const [channelId = ''] = value.split('|')
    return channelId.trim()
}

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

/** For alert notification payloads: id segment and name without leading `#`, defaulting id when missing. */
export function parseSlackTargetForAlertPayload(value: string): { channelId: string; channelName: string } {
    const channelId = getSlackChannelIdFromTargetValue(value)
    const pipe = value.indexOf('|')
    if (pipe === -1) {
        return { channelId, channelName: channelId }
    }
    const rawName = value
        .slice(pipe + 1)
        .trim()
        .replace(/^#/, '')
    return { channelId, channelName: rawName || channelId }
}
