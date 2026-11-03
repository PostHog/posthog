import { useActions, useValues } from 'kea'

import { IconCheck, IconChevronDown, IconRefresh, IconX } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Spinner,
} from '@posthog/quill'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'

const REFRESH_INTERVAL_SECONDS = [900, 1800, 3600]
if (process.env.NODE_ENV === 'development') {
    REFRESH_INTERVAL_SECONDS.unshift(10)
}

function DashboardRefreshStatus(): JSX.Element | null {
    const { itemsLoading, refreshMetrics, dashboardLoadData, effectiveLastRefresh } = useValues(dashboardLogic)
    const isInitialLoad =
        dashboardLoadData?.action === 'initial_load' || dashboardLoadData?.action === 'initial_load_with_variables'

    if (itemsLoading) {
        return (
            <span className="flex items-center gap-1 whitespace-nowrap text-(length:--text-ui) text-muted-foreground">
                <Spinner />
                <span translate="no">
                    {refreshMetrics.total
                        ? `${isInitialLoad ? 'Loaded' : 'Refreshed'} ${refreshMetrics.completed} out of ${refreshMetrics.total}`
                        : `${isInitialLoad ? 'Loading' : 'Refreshing'}…`}
                </span>
            </span>
        )
    }
    if (!effectiveLastRefresh || dayjs().diff(dayjs(effectiveLastRefresh), 'hour') >= 24) {
        return null
    }
    return (
        <span className="flex items-center gap-1 whitespace-nowrap text-(length:--text-ui) text-muted-foreground">
            <span>Last refreshed</span>
            <TZLabel time={effectiveLastRefresh} />
        </span>
    )
}

export function DashboardRefreshAction(): JSX.Element {
    const { itemsLoading, autoRefresh, blockRefresh, nextAllowedDashboardRefresh } = useValues(dashboardLogic)
    const { triggerDashboardRefresh, setAutoRefresh, setPageVisibility, cancelDashboardRefresh } =
        useActions(dashboardLogic)

    usePageVisibilityCb(setPageVisibility)

    const refreshBlocked =
        !itemsLoading &&
        blockRefresh &&
        !!nextAllowedDashboardRefresh &&
        dayjs(nextAllowedDashboardRefresh).isAfter(dayjs())

    return (
        <div data-quill className="flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-1">
            <DashboardRefreshStatus />
            <ButtonGroup>
                <Shortcut
                    name="DashboardRefresh"
                    keybind={[keyBinds.refresh]}
                    intent="Refresh dashboard"
                    interaction="click"
                    scope={Scene.Dashboard}
                >
                    <Button
                        variant="outline"
                        onClick={() => (itemsLoading ? cancelDashboardRefresh() : triggerDashboardRefresh())}
                        tooltip={itemsLoading ? 'Cancel refresh' : undefined}
                        disabledReason={
                            refreshBlocked
                                ? `Next bulk refresh possible ${dayjs(nextAllowedDashboardRefresh).fromNow()}`
                                : undefined
                        }
                        data-attr="dashboard-items-action-refresh"
                    >
                        {itemsLoading ? <IconX /> : refreshBlocked ? <IconCheck /> : <IconRefresh />}
                        {itemsLoading ? 'Cancel' : 'Refresh'}
                    </Button>
                </Shortcut>
                <DropdownMenu modal={false}>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                size={autoRefresh.enabled ? 'default' : 'icon'}
                                aria-label="Auto refresh options"
                                tooltip="Auto refresh"
                            />
                        }
                        data-attr="dashboard-items-action-refresh-dropdown"
                    >
                        {autoRefresh.enabled && (
                            <span translate="no" className="text-muted-foreground">
                                Every {humanFriendlyDuration(autoRefresh.interval)}
                            </span>
                        )}
                        <IconChevronDown />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuCheckboxItem
                            checked={autoRefresh.enabled}
                            onCheckedChange={(checked) => setAutoRefresh(checked, autoRefresh.interval)}
                            data-attr="dashboard-auto-refresh-toggle"
                        >
                            Auto refresh while on page
                        </DropdownMenuCheckboxItem>
                        {autoRefresh.enabled && (
                            <>
                                <DropdownMenuSeparator />
                                <DropdownMenuGroup>
                                    <DropdownMenuLabel>Refresh interval</DropdownMenuLabel>
                                    <DropdownMenuRadioGroup
                                        value={String(autoRefresh.interval)}
                                        onValueChange={(value) => setAutoRefresh(true, Number(value))}
                                    >
                                        {REFRESH_INTERVAL_SECONDS.map((seconds) => (
                                            <DropdownMenuRadioItem key={seconds} value={String(seconds)}>
                                                {humanFriendlyDuration(seconds)}
                                            </DropdownMenuRadioItem>
                                        ))}
                                    </DropdownMenuRadioGroup>
                                </DropdownMenuGroup>
                            </>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            </ButtonGroup>
        </div>
    )
}
