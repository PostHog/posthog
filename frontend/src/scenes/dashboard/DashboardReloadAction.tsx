import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { IconRefresh } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { humanFriendlyDuration } from 'lib/utils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'

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
    const { triggerDashboardRefresh, setAutoRefresh, setPageVisibility, cancelDashboardRefresh } =
        useActions(dashboardLogic)

    usePageVisibilityCb((pageIsVisible) => {
        setPageVisibility(pageIsVisible)
    })

    // Force a re-render when nextAllowedDashboardRefresh is reached, since the blockRefresh
    // selector uses now() which isn't reactive - it only recomputes on dependency changes
    const [, setRenderTrigger] = useState(0)
    useEffect(() => {
        if (nextAllowedDashboardRefresh) {
            const msUntilRefreshAllowed = dayjs(nextAllowedDashboardRefresh).diff(dayjs())
            if (msUntilRefreshAllowed > 0) {
                const timeoutId = setTimeout(() => setRenderTrigger((n) => n + 1), msUntilRefreshAllowed + 100)
                return () => clearTimeout(timeoutId)
            }
        }
    }, [nextAllowedDashboardRefresh])

    const options = INTERVAL_OPTIONS.map((option) => {
        return {
            ...option,
            disabledReason: !autoRefresh.enabled ? 'Enable auto refresh to set the interval' : undefined,
        }
    })

    const refreshDisabledReason =
        !itemsLoading &&
        blockRefresh &&
        nextAllowedDashboardRefresh &&
        dayjs(nextAllowedDashboardRefresh).isAfter(dayjs())
            ? `Next bulk refresh possible ${dayjs(nextAllowedDashboardRefresh).fromNow()}`
            : ''

    return (
        <div className="relative flex items-center gap-2">
            {/* Status text */}
            <span className="text-muted text-sm whitespace-nowrap">
                {itemsLoading ? (
                    <span className="flex items-center gap-1">
                        <Spinner textColored className="text-sm" />
                        {refreshMetrics.total ? (
                            <>
                                {dashboardLoadData?.action === 'initial_load' ? 'Loaded' : 'Refreshed'}{' '}
                                {refreshMetrics.completed} out of {refreshMetrics.total}
                            </>
                        ) : (
                            <>{dashboardLoadData?.action === 'initial_load' ? 'Loading' : 'Refreshing'}...</>
                        )}
                    </span>
                ) : (
                    <LastRefreshText />
                )}
            </span>

            <AppShortcut
                name="DashboardRefresh"
                keybind={[keyBinds.refresh]}
                intent="Refresh dashboard"
                interaction="click"
                scope={Scene.Dashboard}
            >
                <LemonButton
                    onClick={() => (itemsLoading ? cancelDashboardRefresh() : triggerDashboardRefresh())}
                    type="secondary"
                    icon={
                        itemsLoading ? (
                            <IconX />
                        ) : blockRefresh &&
                          nextAllowedDashboardRefresh &&
                          dayjs(nextAllowedDashboardRefresh).isAfter(dayjs()) ? (
                            <IconCheck />
                        ) : (
                            <IconRefresh />
                        )
                    }
                    size="small"
                    data-attr="dashboard-items-action-refresh"
                    tooltip={itemsLoading ? 'Cancel refresh' : undefined}
                    disabledReason={refreshDisabledReason}
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
                                                    onChange={(checked) =>
                                                        setAutoRefresh(checked, autoRefresh.interval)
                                                    }
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
                    {itemsLoading ? 'Cancel' : 'Refresh'}
                </LemonButton>
            </AppShortcut>

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
