import { Radio, Space, RadioChangeEvent } from 'antd'
import { dashboardLogic, DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES } from 'scenes/dashboard/dashboardLogic'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from 'lib/utils'
import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { dayjs } from 'lib/dayjs'
import { LemonButtonWithSideAction, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'

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
            <LemonButtonWithSideAction
                onClick={() => refreshAllDashboardItemsManual()}
                type="secondary"
                status="muted"
                icon={itemsLoading ? <Spinner monocolor={true} /> : <IconRefresh />}
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
                                    <div
                                        id="auto-refresh-check"
                                        key="auto-refresh-check"
                                        onClick={(e) => {
                                            e.preventDefault()
                                            e.stopPropagation()
                                            setAutoRefresh(!autoRefresh.enabled, autoRefresh.interval)
                                        }}
                                    >
                                        <Tooltip title={`Refresh dashboard automatically`} placement="bottomLeft">
                                            <LemonSwitch
                                                onChange={(checked) => setAutoRefresh(checked, autoRefresh.interval)}
                                                label={'Auto refresh'}
                                                checked={autoRefresh.enabled}
                                                fullWidth={true}
                                            />
                                        </Tooltip>
                                    </div>
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
                                            <Space direction="vertical" style={{ width: '100%' }}>
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
                                            </Space>
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
            </LemonButtonWithSideAction>
        </>
    )
}
