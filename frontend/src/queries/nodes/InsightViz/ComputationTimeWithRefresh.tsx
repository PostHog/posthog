import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { Link } from '@posthog/lemon-ui'

export function ComputationTimeWithRefresh(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const showRefreshOnInsight = !!featureFlags[FEATURE_FLAGS.REFRESH_BUTTON_ON_INSIGHT]

    const { lastRefresh } = useValues(dataNodeLogic)

    const { insightProps } = useValues(insightLogic)
    const { getInsightRefreshButtonDisabledReason } = useValues(insightDataLogic(insightProps))
    const { loadData } = useActions(insightDataLogic(insightProps))

    usePeriodicRerender(15000) // Re-render every 15 seconds for up-to-date `insightRefreshButtonDisabledReason`

    return (
        <div className="flex items-center text-muted-alt">
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
            {showRefreshOnInsight && (
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
