import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'

export const RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT = 20

// Slack channel picker values are encoded as `${channelId}|#${channelName}`; callers only ever need the id half.
export function slackChannelId(channelValue: string): string {
    return channelValue.split('|')[0]
}

// Member ids start with U, or W for an Enterprise Grid member. Channel ids start with C, G, or D.
const SLACK_MEMBER_ID_PATTERN = /^[UW][A-Z0-9]{4,}$/

/**
 * `chat.postMessage` opens the direct message when handed a member id, so a member target and a
 * channel target share this format. Mirrors the backend `is_slack_member_target`.
 */
export function isSlackMemberTarget(value: string): boolean {
    return SLACK_MEMBER_ID_PATTERN.test(slackChannelId(value))
}

/**
 * The friendly name half (`#channel-name`) of a `${channelId}|#${channelName}` picker value, for
 * display. Falls back to the raw value when no name is encoded (e.g. a bare channel id). Mirrors
 * the backend `_channel_display_name`.
 */
export function slackChannelDisplayName(channelValue: string): string {
    const pipe = channelValue.indexOf('|')
    if (pipe === -1) {
        return channelValue
    }
    return channelValue.slice(pipe + 1).trim() || channelValue
}

function storageKey(integrationId: number): string | null {
    const teamId = getCurrentTeamIdOrNone()
    if (teamId == null) {
        return null
    }
    return `ph-recent-slack-channels__${teamId}__${integrationId}`
}

export function getRecentSlackChannelIds(integrationId: number): string[] {
    const key = storageKey(integrationId)
    if (!key) {
        return []
    }
    try {
        const stored = window.localStorage.getItem(key)
        const parsed = stored ? JSON.parse(stored) : []
        return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : []
    } catch {
        return []
    }
}

export function recordRecentSlackChannel(integrationId: number, channelId: string): void {
    const key = storageKey(integrationId)
    if (!key || !channelId) {
        return
    }
    const next = [channelId, ...getRecentSlackChannelIds(integrationId).filter((id) => id !== channelId)].slice(
        0,
        RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT
    )
    try {
        window.localStorage.setItem(key, JSON.stringify(next))
    } catch {
        // localStorage may be unavailable (quota, privacy mode); recency is best-effort
    }
}
