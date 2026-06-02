import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'

export const RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT = 20

// Slack channel picker values are encoded as `${channelId}|#${channelName}`; callers only ever need the id half.
export function slackChannelId(channelValue: string): string {
    return channelValue.split('|')[0]
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
