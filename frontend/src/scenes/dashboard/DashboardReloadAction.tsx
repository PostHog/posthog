import { LemonButton, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { Radio, RadioChangeEvent } from 'antd'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils'
import { DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES, dashboardLogic } from 'scenes/dashboard/dashboardLogic'

export const LastRefreshText = (): JSX.Element => {
    const { lastRefreshed } = useValues(dashboardLogic)
    return (
        <span>
            Last updated{' '}
            <span className="font-medium">{lastRefreshed ? dayjs(lastRefreshed).fromNow() : 'a while ago'}</span>
        </span>
    )
}

// in seconds
const intervalOptions = [
    ...Array.from([1800, 3600], (v) => ({
        label: humanFriendlyDuration(v),
        value: v,
    })),
]

export function DashboardReloadAction(): JSX.Element {
    const { itemsLoading, autoRefresh, refreshMetrics, blockRefresh } = useValues(dashboardLogic)
    const { refreshAllDashboardItemsManual, setAutoRefresh } = useActions(dashboardLogic)

    return (
        <>
            <LemonButton
                onClick={() => refreshAllDashboardItemsManual()}
                type="secondary"
                icon={itemsLoading ? <Spinner textColored /> : <IconRefresh />}
                size="small"
                data-attr="dashboard-items-action-refresh"
                disabledReason={
                    blockRefresh
                        ? `Dashboards can only be refreshed every ${DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES} minutes.`
                        : ''
                }
                sideAction={{
                    'data-attr': 'dashboard-items-action-refresh-dropdown',
                    dropdown: {
                        closeOnClickInside: false,
                        placement: 'bottom-end',
                        overlay: (
                            <>
                                <div
                                    className={'flex flex-col px-2 py-1'}
                                    data-attr="auto-refresh-picker"
                                    id="auto-refresh-picker"
                                >
                                    <Tooltip
                                        title="Auto-refresh will only work while this tab is open"
                                        placement="topRight"
                                    >
                                        <div>
                                            <LemonSwitch
                                                onChange={(checked) => setAutoRefresh(checked, autoRefresh.interval)}
                                                label={'Auto refresh'}
                                                checked={autoRefresh.enabled}
                                                fullWidth={true}
                                            />
                                        </div>
                                    </Tooltip>
                                    <LemonDivider />
                                    <div className={'flex flex-col'}>
                                        <div role="heading" className="text-muted mb-2">
                                            Refresh interval
                                        </div>
                                        <Radio.Group
                                            onChange={(e: RadioChangeEvent) => {
                                                setAutoRefresh(true, parseInt(e.target.value))
                                            }}
                                            value={autoRefresh.interval}
                                            style={{ width: '100%' }}
                                        >
                                            <div className="flex flex-col gap-2">
                                                {intervalOptions.map(({ label, value }) => (
                                                    <Radio
                                                        key={value}
                                                        value={value}
                                                        style={{ width: '100%' }}
                                                        disabled={!autoRefresh.enabled}
                                                    >
                                                        {label}
                                                    </Radio>
                                                ))}
                                            </div>
                                        </Radio.Group>
                                    </div>
                                </div>
                            </>
                        ),
                    },
                }}
            >
                <span className={clsx('dashboard-items-action-refresh-text')}>
                    {itemsLoading ? (
                        <>
                            {refreshMetrics.total ? (
                                <>
                                    Refreshed {refreshMetrics.completed} out of {refreshMetrics.total}
                                </>
                            ) : (
                                <>Refreshing...</>
                            )}
                        </>
                    ) : (
                        <LastRefreshText />
                    )}
                </span>
            </LemonButton>
        </>
    )
}
