import { Tooltip } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { agentAttribution } from './agentAttribution'
import { HumanizedActivityLogItem } from './humanizeActivity'

export const AGENT_INTENT_TOOLTIP = 'Self-reported by the agent in the x-posthog-intent request header'

/** Why an agent made a change, and which task to open to read the rest of it. */
export function AgentAttribution({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element | null {
    const attribution = agentAttribution(logItem)
    if (!attribution) {
        return null
    }

    return (
        <div className="text-secondary text-xs flex flex-col gap-0.5" data-attr="activity-log-agent-attribution">
            {attribution.intent && (
                <div>
                    <Tooltip title={AGENT_INTENT_TOOLTIP}>
                        <span className="underline decoration-dotted">Agent intent</span>
                    </Tooltip>{' '}
                    <span className="text-default">{attribution.intent}</span>
                </div>
            )}
            {attribution.taskId && (
                <div>
                    Agent task <Link to={urls.codeTaskLink(attribution.taskId)}>{attribution.taskId}</Link>
                </div>
            )}
        </div>
    )
}
