import { BuiltLogic } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { FLAG_EVALUATIONS_RETENTION_DAYS } from 'scenes/feature-flags/flagEvaluationsTable'

import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema/schema-general'

export interface FlagCallsListProps {
    uniqueKey: string
    attachTo: BuiltLogic
    query: DataTableNode | null
    setQuery: (query: DataTableNode) => void
    reachesPastRetention: boolean
}

export function FlagCallsList({
    uniqueKey,
    attachTo,
    query,
    setQuery,
    reachesPastRetention,
}: FlagCallsListProps): JSX.Element {
    const queryLogicKey = `${uniqueKey}-${attachTo.key}`

    return (
        <>
            {reachesPastRetention && (
                <LemonBanner type="info" className="mb-2">
                    This list shows feature flag calls from the last {FLAG_EVALUATIONS_RETENTION_DAYS} days.
                </LemonBanner>
            )}
            <Query
                uniqueKey={uniqueKey}
                attachTo={attachTo}
                query={query}
                setQuery={setQuery}
                context={{
                    insightProps: {
                        dashboardItemId: `new-${queryLogicKey}`,
                        dataNodeCollectionId: queryLogicKey,
                    },
                    emptyStateHeading: 'No feature flag calls',
                    emptyStateDetail: reachesPastRetention
                        ? `Flag calls are kept for ${FLAG_EVALUATIONS_RETENTION_DAYS} days.`
                        : 'Try widening the date range.',
                }}
            />
        </>
    )
}
