import { useActions, useValues } from 'kea'

import { Link, Tooltip } from '@posthog/lemon-ui'
import { Button, Spinner as QuillSpinner } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'

import { shouldQueryBeAsync } from '~/queries/utils'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

export function ComputationTimeWithRefresh({
    disableRefresh,
    onRefresh,
}: {
    disableRefresh?: boolean
    onRefresh?: () => void
}): JSX.Element | null {
    const { lastRefresh, response, query } = useValues(dataNodeLogic)

    const { insightProps } = useValues(insightLogic)
    const { getInsightRefreshButtonDisabledReason, insightDataLoading } = useValues(insightDataLogic(insightProps))
    const { loadData } = useActions(insightDataLogic(insightProps))
    const disabledReason = getInsightRefreshButtonDisabledReason()

    const { user } = useValues(userLogic)
    const { isDev } = useValues(preflightLogic)
    const canBypassRefreshDisabled = user?.is_staff || user?.is_impersonated || isDev

    const quillSurface = useQuillSurface()

    usePeriodicRerender(15000) // Re-render every 15 seconds for up-to-date `insightRefreshButtonDisabledReason`

    if (!response || (!(response as any).result && !(response as any).results)) {
        return null
    }

    const refresh = (): void => {
        onRefresh?.()
        loadData(shouldQueryBeAsync(query) ? 'force_async' : 'force_blocking')
    }
    const bypassTooltip =
        canBypassRefreshDisabled && disabledReason
            ? `${disabledReason} (you can bypass this due to dev env / staff permissions)`
            : undefined
    const computedAt = lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'

    if (quillSurface) {
        return (
            <div className="z-10 flex items-center">
                <span>Computed&nbsp;</span>
                <span translate="no">{computedAt}</span>
                {!disableRefresh && (
                    <>
                        <span className="px-1">•</span>
                        {insightDataLoading ? (
                            <span className="flex items-center gap-1.5">
                                <QuillSpinner />
                                Refreshing
                            </span>
                        ) : (
                            <Button
                                variant="link"
                                size="inline"
                                onClick={refresh}
                                className={disabledReason ? 'opacity-50' : undefined}
                                tooltip={bypassTooltip}
                                disabledReason={canBypassRefreshDisabled ? undefined : disabledReason}
                            >
                                Refresh
                            </Button>
                        )}
                    </>
                )}
            </div>
        )
    }

    return (
        <div className="flex items-center text-secondary z-10">
            {/* Both halves get their own element so neither is a bare text node React tracks: once a
                page-translation extension replaces such a node with a <font> element, React's writes
                land on the detached node and the time freezes, and removing it throws
                removeChild NotFoundError (react#11538). The relative time also opts out of
                translation, since it is rewritten every 15s. */}
            <span>Computed&nbsp;</span>
            <span translate="no">{computedAt}</span>
            {!disableRefresh && (
                <>
                    <span className="px-1">•</span>
                    {insightDataLoading ? (
                        <span className="flex items-center gap-1.5">
                            <Spinner textColored />
                            Refreshing
                        </span>
                    ) : (
                        <Tooltip title={bypassTooltip}>
                            <Link
                                onClick={refresh}
                                className={disabledReason ? 'opacity-50' : ''}
                                disabledReason={canBypassRefreshDisabled ? '' : disabledReason}
                            >
                                Refresh
                            </Link>
                        </Tooltip>
                    )}
                </>
            )}
        </div>
    )
}
