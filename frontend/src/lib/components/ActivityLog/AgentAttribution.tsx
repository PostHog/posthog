import { Tooltip } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { HumanizedActivityLogItem } from './humanizeActivity'

// Matches AGENT_TRIGGER_JOB_TYPE in posthog/models/activity_logging/activity_log.py. Product
// triggers reuse the same field with a job id that is not an agent run, so the type has to match
// before the run id is rendered as a link to a run.
const AGENT_TRIGGER_JOB_TYPE = 'agent'

const INTENT_TOOLTIP = 'What the agent said it was doing. PostHog records this as stated and does not verify it.'

/** Why an agent made a change, and which run to open to read the rest of it. */
export function AgentAttribution({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element | null {
    const trigger = logItem.unprocessed?.detail.trigger
    if (trigger?.job_type !== AGENT_TRIGGER_JOB_TYPE) {
        return null
    }

    const intent = typeof trigger.payload?.intent === 'string' ? trigger.payload.intent : null
    const runId = trigger.job_id || null
    if (!intent && !runId) {
        return null
    }

    return (
        <div className="flex flex-col gap-0.5 text-xs" data-attr="activity-log-agent-attribution">
            {intent && (
                <div>
                    <Tooltip title={INTENT_TOOLTIP}>
                        <span className="text-secondary">Intent (agent-stated)</span>
                    </Tooltip>{' '}
                    <span className="text-default">{intent}</span>
                </div>
            )}
            {runId && (
                <div>
                    <span className="text-secondary">Run</span>{' '}
                    <Link to={urls.codeTaskLink(runId)} className="font-mono">
                        {runId}
                    </Link>
                </div>
            )}
        </div>
    )
}
