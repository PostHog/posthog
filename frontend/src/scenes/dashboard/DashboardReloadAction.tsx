import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { IconRefresh } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyDuration } from 'lib/utils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

export const LastRefreshText = (): JSX.Element => {
    const { effectiveLastRefresh } = useValues(dashboardLogic)
    return (
        <div className="flex items-center gap-1">
            {effectiveLastRefresh && dayjs().diff(dayjs(effectiveLastRefresh), 'hour') < 24 ? (
                <div className="flex items-center gap-1">
                    <span>Last refreshed</span>
                    <TZLabel time={effectiveLastRefresh} />
                </div>
            ) : (
                'Refresh'
            )}
        </div>
    )
}

const REFRESH_INTERVAL_SECONDS = [1800, 3600]
if (process.env.NODE_ENV === 'development') {
    REFRESH_INTERVAL_SECONDS.unshift(10)
}
const INTERVAL_OPTIONS = Array.from(REFRESH_INTERVAL_SECONDS, (value) => ({
    label: humanFriendlyDuration(value),
    value: value,
}))

export function DashboardReloadAction(): JSX.Element {
    const { itemsLoading, autoRefresh, refreshMetrics, blockRefresh, nextAllowedDashboardRefresh, dashboardLoadData } =
        useValues(dashboardLogic)
    const { triggerDashboardRefresh, setAutoRefresh, setPageVisibility } = useActions(dashboardLogic)

    usePageVisibilityCb((pageIsVisible) => {
        setPageVisibility(pageIsVisible)
    })

    const options = INTERVAL_OPTIONS.map((option) => {
        return {
            ...option,
            disabledReason: !autoRefresh.enabled ? 'Enable auto refresh to set the interval' : undefined,
        }
    })

    return (
        <div className="relative">
            <LemonButton
                onClick={() => triggerDashboardRefresh()}
                type="secondary"
                icon={itemsLoading ? <Spinner textColored /> : blockRefresh ? <IconCheck /> : <IconRefresh />}
                size="small"
                data-attr="dashboard-items-action-refresh"
                disabledReason={
                    blockRefresh
                        ? `Next bulk refresh possible ${dayjs(nextAllowedDashboardRefresh).fromNow()}`
                        : itemsLoading
                          ? 'Loading...'
                          : ''
                }
                sideAction={{
                    'data-attr': 'dashboard-items-action-refresh-dropdown',
                    dropdown: {
                        closeOnClickInside: false,
                        placement: 'bottom-end',
                        overlay: (
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: () => (
                                            <LemonSwitch
                                                onChange={(checked) => setAutoRefresh(checked, autoRefresh.interval)}
                                                label="Auto refresh while on page"
                                                checked={autoRefresh.enabled}
                                                fullWidth
                                                className="mt-1 mb-2"
                                            />
                                        ),
                                    },
                                    {
                                        title: 'Refresh interval',
                                        items: [
                                            {
                                                label: () => (
                                                    <LemonRadio
                                                        value={autoRefresh.interval}
                                                        options={options}
                                                        onChange={(value: number) => {
                                                            setAutoRefresh(true, value)
                                                        }}
                                                        className="mx-2 mb-1"
                                                    />
                                                ),
                                            },
                                        ],
                                    },
                                ]}
                            />
                        ),
                    },
                }}
            >
                <span className={clsx('dashboard-items-action-refresh-text')}>
                    {itemsLoading ? (
                        <>
                            {refreshMetrics.total ? (
                                <>
                                    {dashboardLoadData?.action === 'initial_load' ? 'Loaded' : 'Refreshed'}{' '}
                                    {refreshMetrics.completed} out of {refreshMetrics.total}
                                </>
                            ) : (
                                <>{dashboardLoadData?.action === 'initial_load' ? 'Loading' : 'Refreshing'}...</>
                            )}
                        </>
                    ) : (
                        <LastRefreshText />
                    )}
                </span>
            </LemonButton>
            <LemonBadge
                size="small"
                content={
                    <>
                        <IconRefresh className="mr-0" /> {humanFriendlyDuration(autoRefresh.interval)}
                    </>
                }
                visible={autoRefresh.enabled}
                position="top-right"
                status="muted"
            />
        </div>
    )
}
