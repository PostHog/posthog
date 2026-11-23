import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { PlatformAlertConfigurationApi } from './generated/api.schemas'
import { SOURCE_KINDS, canChangeFromList, listRowMute } from './platformAlertFormat'
import { GROUP_SNOOZE_DURATIONS } from './platformAlertLogic'
import { platformAlertsLogic } from './platformAlertsLogic'

export function PlatformAlertRowMenu({ configuration }: { configuration: PlatformAlertConfigurationApi }): JSX.Element {
    const { updatingAlertId } = useValues(platformAlertsLogic)
    const { snoozeAlert, unsnoozeAlert, setAlertEnabled } = useActions(platformAlertsLogic)

    const snoozed = listRowMute({ kind: 'alert', configuration }, new Date())?.until != null
    const disabledReason = canChangeFromList(configuration)
        ? undefined
        : `Change this alert in ${SOURCE_KINDS[configuration.source_kind].label}`

    return (
        <LemonMenu
            placement="bottom-end"
            items={[
                {
                    items: [
                        {
                            label: 'View alert',
                            to: urls.platformAlert(configuration.id),
                            'data-attr': 'platform-alerts-row-view',
                        },
                    ],
                },
                {
                    items: snoozed
                        ? [
                              {
                                  label: 'Unsnooze',
                                  disabledReason,
                                  onClick: () => unsnoozeAlert(configuration),
                                  'data-attr': 'platform-alerts-row-unsnooze',
                              },
                          ]
                        : GROUP_SNOOZE_DURATIONS.map(({ duration, label, hours }) => ({
                              label: `Snooze for ${label}`,
                              disabledReason: configuration.enabled ? disabledReason : 'Enable the alert first',
                              onClick: () => snoozeAlert(configuration, hours),
                              'data-attr': `platform-alerts-row-snooze-${duration}`,
                          })),
                },
                {
                    items: [
                        {
                            label: configuration.enabled ? 'Disable alert' : 'Enable alert',
                            disabledReason,
                            onClick: () => setAlertEnabled(configuration, !configuration.enabled),
                            'data-attr': 'platform-alerts-row-toggle-enabled',
                        },
                    ],
                },
            ]}
        >
            <LemonButton
                size="xsmall"
                icon={<IconEllipsis />}
                loading={updatingAlertId === configuration.id}
                aria-label={`More options for ${configuration.name}`}
                data-attr="platform-alerts-row-menu"
            />
        </LemonMenu>
    )
}
