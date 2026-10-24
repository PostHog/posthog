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
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import {
    AUTO_REFRESH_INTERVAL_OPTIONS,
    dashboardRefreshDisabledReason,
    dashboardRefreshProgressText,
} from 'scenes/dashboard/dashboardRefreshStatus'
import { Scene } from 'scenes/sceneTypes'

/**
 * One control for the dashboard's refresh state. While tiles load it shows the progress and cancels on
 * click. At rest it refreshes, and the last refresh time and the auto refresh setting sit in its tooltip.
 */
export function QuillDashboardReloadAction(): JSX.Element {
    const {
        itemsLoading,
        autoRefresh,
        blockRefresh,
        nextAllowedDashboardRefresh,
        refreshMetrics,
        dashboardLoadData,
        effectiveLastRefresh,
    } = useValues(dashboardLogic)
    const { triggerDashboardRefresh, setAutoRefresh, setPageVisibility, cancelDashboardRefresh } =
        useActions(dashboardLogic)

    usePageVisibilityCb(setPageVisibility)

    const refreshDisabledReason = dashboardRefreshDisabledReason({
        itemsLoading,
        blockRefresh,
        nextAllowedDashboardRefresh,
    })
    const autoRefreshText = autoRefresh.enabled
        ? `Auto refresh every ${humanFriendlyDuration(autoRefresh.interval)}`
        : null

    // data-attr is pinned: autocapture dashboards count refresh and cancel clicks on it.
    const mainButton = itemsLoading ? (
        <Button
            variant="outline"
            onClick={() => cancelDashboardRefresh()}
            tooltip="Cancel refresh"
            data-attr="dashboard-items-action-refresh"
        >
            <Spinner />
            <span className="whitespace-nowrap" translate="no">
                {dashboardRefreshProgressText(refreshMetrics, dashboardLoadData?.action)}
            </span>
            <IconX />
        </Button>
    ) : (
        <Button
            variant="outline"
            onClick={() => triggerDashboardRefresh()}
            disabledReason={refreshDisabledReason || undefined}
            indicator={autoRefresh.enabled ? 'default' : undefined}
            aria-label={autoRefreshText ? `Refresh. ${autoRefreshText}` : undefined}
            tooltip={
                effectiveLastRefresh || autoRefreshText ? (
                    <div className="flex flex-col gap-1">
                        {effectiveLastRefresh && (
                            <span>
                                Last refreshed <TZLabel time={effectiveLastRefresh} noStyles />
                            </span>
                        )}
                        {autoRefreshText && <span>{autoRefreshText}</span>}
                    </div>
                ) : undefined
            }
            data-attr="dashboard-items-action-refresh"
        >
            {refreshDisabledReason ? <IconCheck /> : <IconRefresh />}
            Refresh
        </Button>
    )

    return (
        <ButtonGroup>
            <Shortcut
                name="DashboardRefresh"
                keybind={[keyBinds.refresh]}
                intent="Refresh dashboard"
                interaction="click"
                scope={Scene.Dashboard}
            >
                {mainButton}
            </Shortcut>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon"
                            aria-label="Auto refresh options"
                            tooltip="Auto refresh options"
                            data-attr="dashboard-items-action-refresh-dropdown"
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuCheckboxItem
                        checked={autoRefresh.enabled}
                        onCheckedChange={(checked) => setAutoRefresh(checked, autoRefresh.interval)}
                        closeOnClick={false}
                    >
                        Auto refresh while on page
                    </DropdownMenuCheckboxItem>
                    {autoRefresh.enabled && (
                        <>
                            <DropdownMenuSeparator />
                            <DropdownMenuGroup>
                                <DropdownMenuLabel>Refresh interval</DropdownMenuLabel>
                                <DropdownMenuRadioGroup
                                    value={autoRefresh.interval}
                                    onValueChange={(value: number) => setAutoRefresh(true, value)}
                                >
                                    {AUTO_REFRESH_INTERVAL_OPTIONS.map(({ label, value }) => (
                                        <DropdownMenuRadioItem key={value} value={value}>
                                            {label}
                                        </DropdownMenuRadioItem>
                                    ))}
                                </DropdownMenuRadioGroup>
                            </DropdownMenuGroup>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </ButtonGroup>
    )
}
