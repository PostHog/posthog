import { IconCheck, IconRefresh, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import type { ShortcutType } from 'lib/components/Shortcuts/shortcutLogic'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import type { Dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { AUTO_REFRESH_INTERVAL_OPTIONS } from './autoRefreshIntervalOptions'
import { QuillDashboardRefreshButton } from './QuillDashboardRefreshButton'

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

export function DashboardRefreshButton(props: DashboardRefreshButtonProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav) {
        return <QuillDashboardRefreshButton {...props} />
    }

    const { loading, onRefresh, onCancel, upToDateReason, autoRefresh, dataAttr, shortcutName, shortcutScope } = props
    const cancellable = loading && !!onCancel

    return (
        <div className="relative inline-flex">
            <Shortcut
                name={shortcutName}
                keybind={[keyBinds.refresh]}
                intent="Refresh dashboard"
                interaction="click"
                scope={shortcutScope}
            >
                <LemonButton
                    onClick={cancellable ? onCancel : onRefresh}
                    type="secondary"
                    icon={cancellable ? <IconX /> : upToDateReason ? <IconCheck /> : <IconRefresh />}
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
                                      overlay: <AutoRefreshMenu autoRefresh={autoRefresh} />,
                                  },
                              }
                            : undefined
                    }
                >
                    {cancellable ? 'Cancel' : 'Refresh'}
                </LemonButton>
            </Shortcut>
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

function AutoRefreshMenu({ autoRefresh }: { autoRefresh: DashboardAutoRefresh }): JSX.Element {
    return (
        <LemonMenuOverlay
            items={[
                {
                    label: () => (
                        <LemonSwitch
                            onChange={(checked) => autoRefresh.onChange(checked, autoRefresh.interval)}
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
                                              onChange={(value: number) => autoRefresh.onChange(true, value)}
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
    )
}
