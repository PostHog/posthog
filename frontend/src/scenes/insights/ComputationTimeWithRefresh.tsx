import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs, now } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { LemonButton } from '@posthog/lemon-ui'

const UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES = 3

export function ComputationTimeWithRefresh(): JSX.Element | null {
    const { lastRefresh, nextAllowedRefresh } = useValues(insightLogic)
    const { loadResults } = useActions(insightLogic)

    usePeriodicRerender(15000)

    let disabledReason = ''

    if (!!nextAllowedRefresh && now().isBefore(dayjs(nextAllowedRefresh))) {
        // If this is a saved insight, the result will contain nextAllowedRefresh and we use that to disable the button
        disabledReason = `You can refresh this insight again ${dayjs(nextAllowedRefresh).fromNow()}`
    } else if (
        !!lastRefresh &&
        now()
            .subtract(UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES - 0.5, 'minutes')
            .isBefore(lastRefresh)
    ) {
        // Unsaved insights don't get cached and get refreshed on every page load, but we avoid allowing users to click
        // 'refresh' more than once every UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES. This can be bypassed by simply
        // refreshing the page though, as there's no cache layer on the backend
        disabledReason = `You can refresh this insight again ${dayjs(lastRefresh)
            .add(UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES, 'minutes')
            .fromNow()}`
    }

    return (
        <div className="flex items-center text-muted-alt">
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
            <span className="px-1">•</span>
            <LemonButton size="small" onClick={() => loadResults(true)} disabledReason={disabledReason} className="p-0">
                <span className="text-sm">Refresh</span>
            </LemonButton>
        </div>
    )
}
