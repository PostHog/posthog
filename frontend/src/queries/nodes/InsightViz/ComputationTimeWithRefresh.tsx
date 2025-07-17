import { Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { shouldQueryBeAsync } from '~/queries/utils'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

export function ComputationTimeWithRefresh({ disableRefresh }: { disableRefresh?: boolean }): JSX.Element | null {
    const { lastRefresh, response, query } = useValues(dataNodeLogic)

    const { insightProps } = useValues(insightLogic)
    const { getInsightRefreshButtonDisabledReason } = useValues(insightDataLogic(insightProps))
    const { loadData } = useActions(insightDataLogic(insightProps))
    const disabledReason = getInsightRefreshButtonDisabledReason()

    const { user } = useValues(userLogic)
    const { isDev } = useValues(preflightLogic)
    const canBypassRefreshDisabled = user?.is_staff || user?.is_impersonated || isDev

    usePeriodicRerender(15000) // Re-render every 15 seconds for up-to-date `insightRefreshButtonDisabledReason`

    if (!response || (!(response as any).result && !(response as any).results)) {
        return null
    }

    return (
        <div className="flex items-center text-secondary z-10">
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
            {!disableRefresh && (
                <>
                    <span className="px-1">•</span>
                    <Tooltip
                        title={
                            canBypassRefreshDisabled && disabledReason
                                ? `${disabledReason} (you can bypass this due to dev env / staff permissions)`
                                : undefined
                        }
                    >
                        <Link
                            onClick={() => loadData(shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')}
                            className={disabledReason ? 'opacity-50' : ''}
                            disabledReason={canBypassRefreshDisabled ? '' : disabledReason}
                        >
                            Refresh
                        </Link>
                    </Tooltip>
                </>
            )}
        </div>
    )
}
