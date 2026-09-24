import { activityClientLabel, isScoutClient } from 'lib/components/ActivityLog/activityClientLabel'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { parseAgentAttribution } from 'lib/components/ActivityLog/parseAgentAttribution'

/**
 * The server stores no IP for a token bound to a sandbox task, and only that binding writes a
 * task id, so intent alone gets no label.
 */
export function sandboxIpLabel(logItem: HumanizedActivityLogItem): string | null {
    const client = logItem.unprocessed?.client
    if (client && isScoutClient(client)) {
        return `Via ${activityClientLabel(client)}`
    }
    return parseAgentAttribution(logItem)?.taskId ? 'Via sandbox' : null
}
