import { IconCheck, IconRefresh, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import type { ShortcutType } from 'lib/components/Shortcuts/shortcutLogic'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
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
    /** Set while the results are too fresh to refresh again. */
    disabledReason?: string
    /** Without it, the button has no auto refresh menu. */
    autoRefresh?: DashboardAutoRefresh
    dataAttr: string
    shortcutName: string
    shortcutScope?: ShortcutType['scope']
}

export function DashboardRefreshButton({
    loading,
    onRefresh,
    onCancel,
    disabledReason,
    autoRefresh,
    dataAttr,
    shortcutName,
    shortcutScope,
}: DashboardRefreshButtonProps): JSX.Element {
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
                    icon={cancellable ? <IconX /> : disabledReason ? <IconCheck /> : <IconRefresh />}
                    size="small"
                    data-attr={dataAttr}
                    loading={loading && !onCancel}
                    tooltip={cancellable ? 'Cancel refresh' : undefined}
                    disabledReason={disabledReason || undefined}
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
