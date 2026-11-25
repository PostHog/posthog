import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { PlatformAlertConfigurationApi } from './generated/api.schemas'
import { SOURCE_KINDS, canChangeFromList, listRowMute } from './platformAlertFormat'
import { GROUP_SNOOZE_DURATIONS } from './platformAlertLogic'
import { platformAlertsLogic } from './platformAlertsLogic'

export function PlatformAlertRowMenu({ configuration }: { configuration: PlatformAlertConfigurationApi }): JSX.Element {
    const { updatingAlertIds } = useValues(platformAlertsLogic)
    const { snoozeAlert, unsnoozeAlert, setAlertEnabled } = useActions(platformAlertsLogic)

    const snoozed = listRowMute({ kind: 'alert', configuration }, new Date())?.kind === 'snoozed'
    const sourceLabel = SOURCE_KINDS[configuration.source_kind].label
    const changeable = canChangeFromList(configuration)
    const editDisabledReason = changeable ? undefined : `Change this alert in ${sourceLabel}`
    const snoozeDisabledReason = changeable
        ? undefined
        : `${snoozed ? 'Unsnooze' : 'Snooze'} this alert in ${sourceLabel}`

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
                                  disabledReason: snoozeDisabledReason,
                                  onClick: () => unsnoozeAlert(configuration),
                                  'data-attr': 'platform-alerts-row-unsnooze',
                              },
                          ]
                        : GROUP_SNOOZE_DURATIONS.map(({ duration, label, hours }) => ({
                              label: `Snooze for ${label}`,
                              disabledReason:
                                  snoozeDisabledReason ??
                                  (configuration.enabled ? undefined : 'Enable the alert first'),
                              onClick: () => snoozeAlert(configuration, hours),
                              'data-attr': `platform-alerts-row-snooze-${duration}`,
                          })),
                },
                {
                    items: [
                        {
                            label: configuration.enabled ? 'Disable alert' : 'Enable alert',
                            disabledReason: editDisabledReason,
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
                loading={updatingAlertIds.has(configuration.id)}
                aria-label={`More options for ${configuration.name}`}
                data-attr="platform-alerts-row-menu"
            />
        </LemonMenu>
    )
}
