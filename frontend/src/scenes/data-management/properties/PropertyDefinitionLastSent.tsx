import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import {
    LastSentState,
    PropertyDefinitionWithUsage,
    formatLastSentDay,
} from 'scenes/data-management/properties/propertyDefinitionsTableLogic'

export interface PropertyDefinitionLastSentProps {
    definition: PropertyDefinitionWithUsage
    lastSentState: LastSentState | null
}

export function PropertyDefinitionLastSent({
    definition,
    lastSentState,
}: PropertyDefinitionLastSentProps): JSX.Element {
    if (lastSentState === 'failed') {
        return (
            <Tooltip title="Couldn't load when properties were last sent. Refresh the page to try again.">
                <span className="text-secondary" data-attr="property-definition-last-sent-failed">
                    —
                </span>
            </Tooltip>
        )
    }
    const { last_sent_status: status, last_sent_at: lastSentAt } = definition
    if (lastSentState === 'computing' && !status) {
        return <LemonSkeleton className="h-4 w-20" />
    }
    if (status === 'sent' && lastSentAt) {
        return (
            <Tooltip title={`Last sent on ${dayjs(lastSentAt).format('MMMM D, YYYY')}`}>
                <span className="whitespace-nowrap" data-attr="property-definition-last-sent">
                    {formatLastSentDay(lastSentAt)}
                </span>
            </Tooltip>
        )
    }
    if (status === 'not_sent_in_30_days') {
        return <span className="text-secondary whitespace-nowrap">Over 30 days ago</span>
    }
    if (status === 'not_tracked') {
        return (
            <Tooltip title="PostHog doesn't record when this property was last sent.">
                <span className="text-secondary">—</span>
            </Tooltip>
        )
    }
    return <span className="text-secondary">—</span>
}
