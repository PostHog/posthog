import { isScoutClient } from 'lib/components/ActivityLog/activityClientLabel'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { parseAgentAttribution } from 'lib/components/ActivityLog/parseAgentAttribution'

export interface SandboxChange {
    /** A scout run's client tag already names the scout, so only other sandbox tasks need a tag. */
    needsSandboxTag: boolean
}

/** Only the server binds a token to a sandbox task and writes its task id, so intent alone does not count. */
export function sandboxChange(logItem: HumanizedActivityLogItem): SandboxChange | null {
    if (!parseAgentAttribution(logItem)?.taskId) {
        return null
    }
    const client = logItem.unprocessed?.client
    return { needsSandboxTag: !(client && isScoutClient(client)) }
}
