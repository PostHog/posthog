import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { HumanizedActivityLogItem } from './humanizeActivity'
import { parseAgentAttribution } from './parseAgentAttribution'

export const AGENT_INTENT_TOOLTIP = 'Self-reported by the agent in the x-posthog-intent request header'

export function AgentAttribution({
    logItem,
    truncateIntent = false,
}: {
    logItem: HumanizedActivityLogItem
    truncateIntent?: boolean
}): JSX.Element | null {
    const attribution = parseAgentAttribution(logItem)
    if (!attribution) {
        return null
    }

    return (
        <div className="text-secondary text-xs flex flex-col gap-0.5" data-attr="activity-log-agent-attribution">
            {attribution.intent && (
                <div className={clsx(truncateIntent && 'line-clamp-1')}>
                    <Tooltip title={AGENT_INTENT_TOOLTIP}>
                        <span className="underline decoration-dotted">Agent intent</span>
                    </Tooltip>{' '}
                    <span className="text-default">{attribution.intent}</span>
                </div>
            )}
            {attribution.taskId && (
                <div>
                    Agent task{' '}
                    <Link to={urls.codeTaskLink(attribution.taskId)} target="_blank" targetBlankIcon>
                        {attribution.taskId.slice(0, 8)}
                    </Link>
                </div>
            )}
        </div>
    )
}
