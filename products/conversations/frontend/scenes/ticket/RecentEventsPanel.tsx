import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema/schema-general'
import { PersonsTabType } from '~/types'

interface RecentEventsPanelProps {
    eventsQuery: DataTableNode | null
    personLoading?: boolean
    distinctId?: string
    sessionId?: string
}

export function RecentEventsPanel({
    eventsQuery,
    personLoading,
    distinctId,
    sessionId,
}: RecentEventsPanelProps): JSX.Element {
    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'recent-events',
                    header: (
                        <>
                            Recent events
                            {eventsQuery && (
                                <span className="text-muted-alt font-normal ml-1">
                                    {sessionId ? '(session)' : '(±5 min)'}
                                </span>
                            )}
                        </>
                    ),
                    content: (
                        <div>
                            {personLoading ? (
                                <div className="text-muted-alt text-xs">Loading events...</div>
                            ) : eventsQuery ? (
                                <div className="max-h-96 overflow-auto">
                                    <Query query={eventsQuery} filtersOverride={null} />
                                </div>
                            ) : (
                                <div className="text-muted-alt text-xs">No recent events found</div>
                            )}
                            {distinctId && (
                                <div className="mt-2 pt-2 border-t flex justify-end">
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        to={`${urls.personByDistinctId(distinctId)}#activeTab=${PersonsTabType.EVENTS}`}
                                    >
                                        See all events →
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
