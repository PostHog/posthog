import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { LemonButton } from '@posthog/lemon-ui'

export function ComputationTimeWithRefresh(): JSX.Element | null {
    const { lastRefresh, insightRefreshButtonDisabledReason } = useValues(insightLogic)
    const { loadResults } = useActions(insightLogic)

    usePeriodicRerender(15000)

    return (
        <div className="flex items-center text-muted-alt">
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
            <span className="px-1">•</span>
            <LemonButton
                size="small"
                onClick={() => loadResults(true)}
                disabledReason={insightRefreshButtonDisabledReason}
                className="p-0"
            >
                <span className="text-sm">Refresh</span>
            </LemonButton>
        </div>
    )
}
