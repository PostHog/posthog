import { HumanizedActivityLogItem } from './humanizeActivity'

// Matches AGENT_TRIGGER_JOB_TYPE in posthog/models/activity_logging/activity_log.py. Product
// triggers carry job ids that are not sandbox tasks, so only this job type links to a task.
const AGENT_TRIGGER_JOB_TYPE = 'agent'

export interface AgentAttribution {
    /** Self-reported by the agent, never verified. */
    intent: string | null
    /** Bound to the agent's token by the server, so a row without it is not an agent write. */
    taskId: string
}

export function parseAgentAttribution(logItem: HumanizedActivityLogItem): AgentAttribution | null {
    const trigger = logItem.unprocessed?.detail?.trigger
    if (trigger?.job_type !== AGENT_TRIGGER_JOB_TYPE || !trigger.job_id) {
        return null
    }

    return {
        intent: typeof trigger.payload?.intent === 'string' ? trigger.payload.intent : null,
        taskId: trigger.job_id,
    }
}
