import { isScoutClient } from 'lib/components/ActivityLog/activityClientLabel'
import { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { parseAgentAttribution } from 'lib/components/ActivityLog/parseAgentAttribution'

export interface SandboxChange {
    /** A scout run's client tag already names the scout, so only other sandbox tasks need a tag. */
    needsSandboxTag: boolean
}

/**
 * The row used a token bound to a sandbox task. The token can leave the sandbox, so this says which
 * token made the change, not where the request came from. Only that binding writes a task id.
 */
export function sandboxChange(logItem: HumanizedActivityLogItem): SandboxChange | null {
    if (!parseAgentAttribution(logItem)?.taskId) {
        return null
    }
    const client = logItem.unprocessed?.client
    return { needsSandboxTag: !(client && isScoutClient(client)) }
}
