import { Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

export function ComputationTimeWithRefresh({ disableRefresh }: { disableRefresh?: boolean }): JSX.Element | null {
    const { lastRefresh, response } = useValues(dataNodeLogic)

    const { insightProps } = useValues(insightLogic)
    const { getInsightRefreshButtonDisabledReason } = useValues(insightDataLogic(insightProps))
    const { loadData } = useActions(insightDataLogic(insightProps))

    usePeriodicRerender(15000) // Re-render every 15 seconds for up-to-date `insightRefreshButtonDisabledReason`

    if (!response || (!response.result && !response.results)) {
        return null
    }

    return (
        <div className="flex items-center text-muted-alt z-10">
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
            {!disableRefresh && (
                <>
                    <span className="px-1">•</span>
                    <Link disabledReason={getInsightRefreshButtonDisabledReason()} onClick={() => loadData(true)}>
                        Refresh
                    </Link>
                </>
            )}
        </div>
    )
}
