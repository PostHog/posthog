import { useActions, useValues } from 'kea'

import { IconCheck, IconChevronDown, IconRefresh, IconX } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'

import { AUTO_REFRESH_INTERVAL_OPTIONS } from './autoRefreshIntervalOptions'

export interface QuillDashboardReloadActionProps {
    refreshDisabledReason: string
    onRefreshClick: () => void
}

export function QuillDashboardReloadAction({
    refreshDisabledReason,
    onRefreshClick,
}: QuillDashboardReloadActionProps): JSX.Element {
    const { itemsLoading, autoRefresh } = useValues(dashboardLogic)
    const { setAutoRefresh } = useActions(dashboardLogic)

    const optionsLabel = autoRefresh.enabled
        ? `Refresh options (auto refresh every ${humanFriendlyDuration(autoRefresh.interval)})`
        : 'Refresh options'

    return (
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
                    onClick={onRefreshClick}
                    data-attr="dashboard-items-action-refresh"
                    tooltip={itemsLoading ? 'Cancel refresh' : undefined}
                    disabledReason={refreshDisabledReason || undefined}
                >
                    {itemsLoading ? <IconX /> : refreshDisabledReason ? <IconCheck /> : <IconRefresh />}
                    {itemsLoading ? 'Cancel' : 'Refresh'}
                </Button>
            </Shortcut>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon"
                            aria-label={optionsLabel}
                            tooltip={optionsLabel}
                            indicator={autoRefresh.enabled ? 'default' : undefined}
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
                    >
                        Auto refresh while on page
                    </DropdownMenuCheckboxItem>
                    {autoRefresh.enabled && (
                        <>
                            <DropdownMenuSeparator />
                            <DropdownMenuRadioGroup
                                value={String(autoRefresh.interval)}
                                onValueChange={(value) => setAutoRefresh(true, Number(value))}
                            >
                                <DropdownMenuLabel>Refresh interval</DropdownMenuLabel>
                                {AUTO_REFRESH_INTERVAL_OPTIONS.map((option) => (
                                    <DropdownMenuRadioItem key={option.value} value={String(option.value)}>
                                        {option.label}
                                    </DropdownMenuRadioItem>
                                ))}
                            </DropdownMenuRadioGroup>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </ButtonGroup>
    )
}
