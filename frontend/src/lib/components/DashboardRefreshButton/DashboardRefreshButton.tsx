import { IconCheck, IconChevronDown, IconRefresh, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSwitch } from '@posthog/lemon-ui'
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
import type { ShortcutType } from 'lib/components/Shortcuts/shortcutLogic'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TZLabel } from 'lib/components/TZLabel'
import type { Dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { AUTO_REFRESH_INTERVAL_OPTIONS } from './autoRefreshIntervalOptions'

export interface DashboardAutoRefresh {
    enabled: boolean
    interval: number
    onChange: (enabled: boolean, interval: number) => void
}

export interface DashboardRefreshButtonProps {
    loading: boolean
    onRefresh: () => void
    /** Without it, a running refresh shows as loading instead of offering to cancel. */
    onCancel?: () => void
    /** Disables the button and marks the results as up to date. */
    upToDateReason?: string
    /** Without it, the button has no auto refresh menu. */
    autoRefresh?: DashboardAutoRefresh
    dataAttr: string
    shortcutName: string
    shortcutScope?: ShortcutType['scope']
    lastRefresh?: Dayjs | string | null
}

export function DashboardRefreshButton({
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const cancellable = loading && !!onCancel
    // Called without the click event, so a handler's optional first argument stays unset.
    const onClick = (): void => (cancellable ? onCancel?.() : onRefresh())
    const icon = cancellable ? <IconX /> : upToDateReason ? <IconCheck /> : <IconRefresh />
    const label = cancellable ? 'Cancel' : 'Refresh'
    const withShortcut = (button: JSX.Element): JSX.Element => (
        <Shortcut
            name={shortcutName}
            keybind={[keyBinds.refresh]}
            intent="Refresh dashboard"
            interaction="click"
            scope={shortcutScope}
        >
            {button}
        </Shortcut>
    )

    if (todayRailNav) {
        const optionsLabel = autoRefresh?.enabled
            ? `Refresh options (auto refresh every ${humanFriendlyDuration(autoRefresh.interval)})`
            : 'Refresh options'
        return (
            <ButtonGroup>
                {withShortcut(
                    <Button
                        variant="outline"
                        onClick={onClick}
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
                        {icon}
                        <span>{label}</span>
                    </Button>
                )}
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

    return (
        <div className="relative inline-flex">
            {withShortcut(
                <LemonButton
                    onClick={onClick}
                    type="secondary"
                    icon={icon}
                    size="small"
                    data-attr={dataAttr}
                    loading={loading && !onCancel}
                    tooltip={cancellable ? 'Cancel refresh' : undefined}
                    disabledReason={upToDateReason}
                    sideAction={
                        autoRefresh
                            ? {
                                  'data-attr': `${dataAttr}-dropdown`,
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
                                                                  autoRefresh.onChange(checked, autoRefresh.interval)
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
                                                                                options={AUTO_REFRESH_INTERVAL_OPTIONS}
                                                                                onChange={(value: number) =>
                                                                                    autoRefresh.onChange(true, value)
                                                                                }
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
                              }
                            : undefined
                    }
                >
                    {label}
                </LemonButton>
            )}
            {autoRefresh && (
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
            )}
        </div>
    )
}
