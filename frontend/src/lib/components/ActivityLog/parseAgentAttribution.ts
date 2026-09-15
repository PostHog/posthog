import { HumanizedActivityLogItem } from './humanizeActivity'

// Matches AGENT_TRIGGER_JOB_TYPE in posthog/models/activity_logging/activity_log.py. Products
// reuse `detail.trigger` with job ids that are not sandbox tasks, so the job type has to match
// before the id is rendered as a link to a task.
const AGENT_TRIGGER_JOB_TYPE = 'agent'

export interface AgentAttribution {
    /** What the agent said it was doing. Self-reported, never verified. */
    intent: string | null
    /** The sandbox task the agent ran under, or null for an agent that runs outside one. */
    taskId: string | null
}

/** The agent context behind one activity row, or null when a person or a product made the change. */
export function parseAgentAttribution(logItem: HumanizedActivityLogItem): AgentAttribution | null {
    const trigger = logItem.unprocessed?.detail?.trigger
    if (trigger?.job_type !== AGENT_TRIGGER_JOB_TYPE) {
        return null
    }

    const intent = typeof trigger.payload?.intent === 'string' ? trigger.payload.intent : null
    const taskId = trigger.job_id || null
    return intent || taskId ? { intent, taskId } : null
}
