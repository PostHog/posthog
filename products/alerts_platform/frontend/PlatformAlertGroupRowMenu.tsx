import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { PlatformAlertApi, PlatformAlertConfigurationApi } from './generated/api.schemas'
import { SOURCE_KINDS, canSnoozeGroups, describeGroup, listRowMute } from './platformAlertFormat'
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
    const snoozed = listRowMute({ kind: 'group', configuration, group }, now)?.until != null
    // The API reports a group's snooze as the later of its own and the alert's, so a group cannot leave an alert's snooze.
    const alertSnoozed = listRowMute({ kind: 'alert', configuration }, now)?.until != null
    let disabledReason: string | undefined
    if (!canSnoozeGroups(configuration)) {
        disabledReason = `Snooze this group in ${SOURCE_KINDS[configuration.source_kind].label}`
    } else if (alertSnoozed) {
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
