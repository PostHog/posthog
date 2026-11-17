import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { PlatformAlertApi } from './generated/api.schemas'
import { GROUP_SNOOZE_EXPLANATION } from './platformAlertFormat'
import { GROUP_SNOOZE_DURATIONS, platformAlertLogic } from './platformAlertLogic'

export function PlatformAlertGroupSnoozeMenu({ alert }: { alert: PlatformAlertApi }): JSX.Element {
    const { snoozingGroupKey, alertSnoozeUntil } = useValues(platformAlertLogic)
    const { snoozeGroupFor, unsnoozeGroup, openCustomSnooze } = useActions(platformAlertLogic)

    const activeSnoozeUntil =
        alert.snooze_until !== null && dayjs(alert.snooze_until).isAfter(dayjs()) ? alert.snooze_until : null
    const snoozed = activeSnoozeUntil !== null
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
                    footer: <p className="text-xs text-secondary max-w-60 m-0 px-2 py-1">{GROUP_SNOOZE_EXPLANATION}</p>,
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
                tooltip={
                    activeSnoozeUntil ? (
                        <>
                            Snoozed until{' '}
                            <TZLabel time={activeSnoozeUntil} timestampStyle="absolute" showPopover={false} />
                        </>
                    ) : undefined
                }
                disabledReason={
                    alertSnoozeUntil
                        ? `The whole alert is snoozed until ${humanFriendlyDetailedTime(alertSnoozeUntil)}. Unsnooze the alert to snooze its groups one at a time.`
                        : snoozingGroupKey !== null && !inFlight
                          ? 'Wait for the other group to finish saving'
                          : undefined
                }
                data-attr="platform-alert-group-snooze-menu"
            >
                {snoozed ? 'Snoozed' : 'Snooze'}
            </LemonButton>
        </LemonMenu>
    )
}
