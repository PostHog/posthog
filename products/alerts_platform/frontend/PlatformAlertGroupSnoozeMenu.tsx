import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { PlatformAlertApi } from './generated/api.schemas'
import { GROUP_SNOOZE_DURATIONS, platformAlertLogic } from './platformAlertLogic'

export function PlatformAlertGroupSnoozeMenu({ alert }: { alert: PlatformAlertApi }): JSX.Element {
    const { snoozingGroupKey } = useValues(platformAlertLogic)
    const { snoozeGroupFor, unsnoozeGroup, openCustomSnooze } = useActions(platformAlertLogic)

    const snoozed = alert.snooze_until !== null && dayjs(alert.snooze_until).isAfter(dayjs())
    const inFlight = snoozingGroupKey === alert.grouping_key

    return (
        <LemonMenu
            items={[
                {
                    title: 'Hold notifications for',
                    items: [
                        ...GROUP_SNOOZE_DURATIONS.map(({ duration, label }) => ({
                            label,
                            onClick: () => snoozeGroupFor(alert.grouping_key, duration),
                            'data-attr': `platform-alert-group-snooze-${duration}`,
                        })),
                        {
                            label: 'Custom time…',
                            onClick: () => openCustomSnooze(alert.grouping_key),
                            'data-attr': 'platform-alert-group-snooze-custom',
                        },
                    ],
                    footer: (
                        <p className="text-xs text-secondary max-w-60 m-0 px-2 py-1">
                            The group keeps being checked, and a firing group stays firing. Only its notifications are
                            held.
                        </p>
                    ),
                },
                snoozed
                    ? {
                          items: [
                              {
                                  label: 'Unsnooze',
                                  onClick: () => unsnoozeGroup(alert.grouping_key),
                                  'data-attr': 'platform-alert-group-unsnooze',
                              },
                          ],
                      }
                    : null,
            ]}
        >
            <LemonButton
                type="secondary"
                size="xsmall"
                sideIcon={<IconChevronDown />}
                loading={inFlight}
                disabledReason={
                    snoozingGroupKey !== null && !inFlight ? 'Wait for the other group to finish saving' : undefined
                }
                data-attr="platform-alert-group-snooze-menu"
            >
                {snoozed ? 'Snoozed' : 'Snooze'}
            </LemonButton>
        </LemonMenu>
    )
}
