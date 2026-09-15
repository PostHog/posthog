import { HumanizedActivityLogItem } from './humanizeActivity'

// Matches AGENT_TRIGGER_JOB_TYPE in posthog/models/activity_logging/activity_log.py. Products
// reuse `detail.trigger` with job ids that are not sandbox tasks, so the job type has to match
// before the id is rendered as a link to a task.
const AGENT_TRIGGER_JOB_TYPE = 'agent'

export interface AgentAttribution {
    /** What the agent said it was doing. Self-reported, never verified. */
    intent: string | null
    /** The sandbox task the agent ran under. Bound to the agent's token, so it is not self-reported. */
    taskId: string
}

/**
 * The agent context behind one activity row, or null when a person or a product made the change.
 *
 * The task id is required, not optional: it is the part of the trigger the server sets, so a row
 * without it is not evidence that an agent made the change and must not be presented as one.
 */
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
