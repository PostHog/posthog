import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { PlatformAlertApi, PlatformAlertConfigurationApi, PlatformAlertOwnerEnumApi } from './generated/api.schemas'
import {
    SOURCE_KINDS,
    canSnoozeGroups,
    describeGroup,
    groupSnoozeLockedByAlert,
    listRowMute,
} from './platformAlertFormat'
import { GROUP_SNOOZE_DURATIONS } from './platformAlertLogic'
import { platformAlertsLogic } from './platformAlertsLogic'

export function PlatformAlertGroupRowMenu({
    configuration,
    group,
}: {
    configuration: PlatformAlertConfigurationApi
    group: PlatformAlertApi
}): JSX.Element {
    const { updatingAlertIds } = useValues(platformAlertsLogic)
    const { snoozeGroup, unsnoozeGroup } = useActions(platformAlertsLogic)

    const now = new Date()
    const snoozed = listRowMute({ kind: 'group', configuration, group }, now)?.kind === 'snoozed'
    let disabledReason: string | undefined
    if (configuration.owner !== PlatformAlertOwnerEnumApi.Platform) {
        disabledReason = `${SOURCE_KINDS[configuration.source_kind].label} manages this alert, so snooze the whole alert there`
    } else if (!canSnoozeGroups(configuration)) {
        disabledReason = 'This alert is not grouped, so snooze the whole alert'
    } else if (groupSnoozeLockedByAlert(configuration, now)) {
        disabledReason = 'The whole alert is snoozed'
    }

    return (
        <LemonMenu
            placement="bottom-end"
            items={
                snoozed
                    ? [
                          {
                              label: 'Unsnooze group',
                              disabledReason,
                              onClick: () => unsnoozeGroup(configuration, group),
                              'data-attr': 'platform-alerts-group-row-unsnooze',
                          },
                      ]
                    : GROUP_SNOOZE_DURATIONS.map(({ duration, label, hours }) => ({
                          label: `Snooze group for ${label}`,
                          disabledReason,
                          onClick: () => snoozeGroup(configuration, group, duration, hours),
                          'data-attr': `platform-alerts-group-row-snooze-${duration}`,
                      }))
            }
        >
            <LemonButton
                size="xsmall"
                icon={<IconEllipsis />}
                loading={updatingAlertIds.has(group.id)}
                aria-label={`More options for ${describeGroup(group, configuration.grouping.keys ?? [])}`}
                data-attr="platform-alerts-group-row-menu"
            />
        </LemonMenu>
    )
}
