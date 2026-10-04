import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { shouldQueryBeAsync } from '~/queries/utils'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

export function ComputationTimeWithRefresh({ disableRefresh }: { disableRefresh?: boolean }): JSX.Element | null {
    const { lastRefresh, response, query } = useValues(dataNodeLogic)

    const { insightProps } = useValues(insightLogic)
    const { getInsightRefreshButtonDisabledReason, insightDataLoading } = useValues(insightDataLogic(insightProps))
    const { loadData } = useActions(insightDataLogic(insightProps))
    const disabledReason = getInsightRefreshButtonDisabledReason()

    const { user } = useValues(userLogic)
    const { isDev } = useValues(preflightLogic)
    const canBypassRefreshDisabled = user?.is_staff || user?.is_impersonated || isDev

    usePeriodicRerender(15000) // Re-render every 15 seconds for up-to-date `insightRefreshButtonDisabledReason`

    const hasResult = !!response && !!((response as any).result || (response as any).results)
    const refreshLabel = insightDataLoading ? 'Refreshing' : 'Refresh'
    const refreshDisabledReason = insightDataLoading
        ? refreshLabel
        : canBypassRefreshDisabled
          ? undefined
          : disabledReason || undefined

    // An insight that came back empty or failed still gets the refresh button, because that is the
    // state people most want to retry from.
    if (!hasResult && disableRefresh) {
        return null
    }

    return (
        <div className="flex items-center gap-2 text-secondary z-10">
            {hasResult && (
                <div className="flex items-center">
                    {/* Both halves get their own element so neither is a bare text node React tracks: once a
                        page-translation extension replaces such a node with a <font> element, React's writes
                        land on the detached node and the time freezes, and removing it throws
                        removeChild NotFoundError (react#11538). The relative time also opts out of
                        translation, since it is rewritten every 15s. */}
                    <span>Computed&nbsp;</span>
                    <span translate="no">{lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}</span>
                </div>
            )}
            {!disableRefresh && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => loadData(shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')}
                    // Setting the loading icon manually to keep the label in place while spinning.
                    icon={insightDataLoading ? <Spinner textColored /> : <IconRefresh />}
                    disabledReason={refreshDisabledReason}
                    tooltip={
                        canBypassRefreshDisabled && disabledReason
                            ? `${disabledReason} (you can bypass this due to dev env / staff permissions)`
                            : undefined
                    }
                >
                    {refreshLabel}
                </LemonButton>
            )}
        </div>
    )
}
