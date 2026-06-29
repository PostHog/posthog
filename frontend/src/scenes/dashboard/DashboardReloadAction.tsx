import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { IconRefresh } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'

export const LastRefreshText = (): JSX.Element => {
    const { effectiveLastRefresh } = useValues(dashboardLogic)
    return (
        <div className="flex items-center gap-1">
            {effectiveLastRefresh && dayjs().diff(dayjs(effectiveLastRefresh), 'hour') < 24 && (
                <div className="flex items-center gap-1">
                    <span>Last refreshed</span>
                    <TZLabel time={effectiveLastRefresh} />
                </div>
            )}
        </div>
    )
}

/** Loading / progress / pessimistic last refresh — same as the left side of `DashboardReloadAction`, without refresh controls. */
export function DashboardRefreshStatusText(): JSX.Element {
    const { itemsLoading, refreshMetrics, dashboardLoadData } = useValues(dashboardLogic)
    const isInitialLoad =
        dashboardLoadData?.action === 'initial_load' || dashboardLoadData?.action === 'initial_load_with_variables'
    return (
        <span className="text-muted text-sm whitespace-nowrap">
            {itemsLoading ? (
                <span className="flex items-center gap-1">
                    <Spinner textColored className="text-sm" />
                    {refreshMetrics.total ? (
                        <>
                            {isInitialLoad ? 'Loaded' : 'Refreshed'} {refreshMetrics.completed} out of{' '}
                            {refreshMetrics.total}
                        </>
                    ) : (
                        <>{isInitialLoad ? 'Loading' : 'Refreshing'}...</>
                    )}
                </span>
            ) : (
                <LastRefreshText />
            )}
        </span>
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
    const { itemsLoading, autoRefresh, blockRefresh, nextAllowedDashboardRefresh } = useValues(dashboardLogic)
    const { triggerDashboardRefresh, setAutoRefresh, setPageVisibility, cancelDashboardRefresh } =
        useActions(dashboardLogic)

    usePageVisibilityCb(setPageVisibility)

    const refreshDisabledReason =
        !itemsLoading &&
        blockRefresh &&
        nextAllowedDashboardRefresh &&
        dayjs(nextAllowedDashboardRefresh).isAfter(dayjs())
            ? `Next bulk refresh possible ${dayjs(nextAllowedDashboardRefresh).fromNow()}`
            : ''

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

    return (
        <div className="relative flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 sm:flex-nowrap">
            <DashboardRefreshStatusText />

            <Shortcut
                name="DashboardRefresh"
                keybind={[keyBinds.refresh]}
                intent="Refresh dashboard"
                interaction="click"
                scope={Scene.Dashboard}
            >
                <div className="relative inline-flex">
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
                                            ...(autoRefresh.enabled
                                                ? [
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
                                                  ]
                                                : []),
                                        ]}
                                    />
                                ),
                            },
                        }}
                    >
                        {itemsLoading ? 'Cancel' : 'Refresh'}
                    </LemonButton>
                </div>
            </Shortcut>

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
