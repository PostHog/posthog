import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { shouldQueryBeAsync } from '~/queries/utils'

import { insightVizDataNodeKey } from './InsightViz'

export function ComputationTimeWithRefresh({ disableRefresh }: { disableRefresh?: boolean }): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { lastRefresh, response, query, getInsightRefreshButtonDisabledReason } = useValues(
        dataNodeLogic({ key: insightVizDataNodeKey(insightProps) } as DataNodeLogicProps)
    )

    const { loadData } = useActions(insightDataLogic(insightProps))
    const disabledReason = getInsightRefreshButtonDisabledReason()

    const { user } = useValues(userLogic)
    const { isDev } = useValues(preflightLogic)
    const canBypassRefreshDisabled = user?.is_staff || user?.is_impersonated || isDev

    usePeriodicRerender(15000) // Re-render every 15 seconds for up-to-date `insightRefreshButtonDisabledReason`

    if (!response || (!(response as any).result && !(response as any).results)) {
        return null
    }

    const computedText = `Computed ${lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}`

    return (
        <div className="flex items-center gap-2">
            <span className="text-secondary text-sm whitespace-nowrap">{computedText}</span>
            {!disableRefresh && (
                <Tooltip
                    title={
                        canBypassRefreshDisabled && disabledReason
                            ? `${disabledReason} (you can bypass this due to dev env / staff permissions)`
                            : undefined
                    }
                >
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={() => loadData(shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')}
                        disabledReason={canBypassRefreshDisabled ? '' : disabledReason}
                        className={canBypassRefreshDisabled && disabledReason ? 'opacity-50' : undefined}
                        data-attr="insight-refresh-button"
                    >
                        Refresh
                    </LemonButton>
                </Tooltip>
            )}
        </div>
    )
}
