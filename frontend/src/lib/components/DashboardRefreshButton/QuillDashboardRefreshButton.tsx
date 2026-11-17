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
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { AUTO_REFRESH_INTERVAL_OPTIONS } from './autoRefreshIntervalOptions'
import type { DashboardRefreshButtonProps } from './DashboardRefreshButton'

export function QuillDashboardRefreshButton({
    loading,
    onRefresh,
    onCancel,
    upToDateReason,
    autoRefresh,
    dataAttr,
    shortcutName,
    shortcutScope,
    lastRefresh,
}: DashboardRefreshButtonProps): JSX.Element {
    const cancellable = loading && !!onCancel
    const optionsLabel = autoRefresh?.enabled
        ? `Refresh options (auto refresh every ${humanFriendlyDuration(autoRefresh.interval)})`
        : 'Refresh options'

    return (
        <ButtonGroup>
            <Shortcut
                name={shortcutName}
                keybind={[keyBinds.refresh]}
                intent="Refresh dashboard"
                interaction="click"
                scope={shortcutScope}
            >
                <Button
                    variant="outline"
                    onClick={cancellable ? onCancel : onRefresh}
                    loading={loading && !onCancel}
                    data-attr={dataAttr}
                    tooltip={
                        cancellable ? (
                            'Cancel refresh'
                        ) : lastRefresh ? (
                            <span>
                                <span>Last refreshed </span>
                                <TZLabel time={lastRefresh} showPopover={false} noStyles />
                            </span>
                        ) : undefined
                    }
                    disabledReason={upToDateReason}
                >
                    {cancellable ? <IconX /> : upToDateReason ? <IconCheck /> : <IconRefresh />}
                    <span>{cancellable ? 'Cancel' : 'Refresh'}</span>
                </Button>
            </Shortcut>
            {autoRefresh && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                size="icon"
                                aria-label={optionsLabel}
                                tooltip={optionsLabel}
                                indicator={autoRefresh.enabled ? 'default' : undefined}
                                data-attr={`${dataAttr}-dropdown`}
                            />
                        }
                    >
                        <IconChevronDown />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuCheckboxItem
                            checked={autoRefresh.enabled}
                            onCheckedChange={(checked) => autoRefresh.onChange(checked, autoRefresh.interval)}
                        >
                            Auto refresh while on page
                        </DropdownMenuCheckboxItem>
                        {autoRefresh.enabled && (
                            <>
                                <DropdownMenuSeparator />
                                <DropdownMenuRadioGroup
                                    value={String(autoRefresh.interval)}
                                    onValueChange={(value) => autoRefresh.onChange(true, Number(value))}
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
            )}
        </ButtonGroup>
    )
}
