import { useValues } from 'kea'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { PlatformAlertApi } from './generated/api.schemas'
import { OptionalTimeLabel } from './OptionalTimeLabel'
import { PlatformAlertGroupCell } from './PlatformAlertGroupCell'
import { PlatformAlertGroupSnoozeMenu } from './PlatformAlertGroupSnoozeMenu'
import { platformAlertLogic } from './platformAlertLogic'
import { PlatformAlertStatusTag } from './PlatformAlertStatusTag'

export function PlatformAlertGroupsTable({
    alerts,
    groupingKeys,
}: {
    alerts: readonly PlatformAlertApi[]
    groupingKeys: readonly string[]
}): JSX.Element {
    const { canSnoozeGroups } = useValues(platformAlertLogic)

    const columns: LemonTableColumns<PlatformAlertApi> = [
        {
            title: 'Group',
            dataIndex: 'grouping_key',
            render: (_, alert) => <PlatformAlertGroupCell alert={alert} groupingKeys={groupingKeys} />,
        },
        {
            title: 'State',
            dataIndex: 'state',
            render: (_, alert) => <PlatformAlertStatusTag status={alert.state} />,
        },
        {
            title: 'Firing since',
            render: (_, alert) => <OptionalTimeLabel time={alert.firing_started_at} fallback="Not firing" />,
        },
        {
            title: 'Last notified',
            className: 'hidden @min-[48rem]/alert-groups:table-cell',
            render: (_, alert) => <OptionalTimeLabel time={alert.last_notified_at} fallback="Never" />,
        },
        {
            title: 'Snoozed until',
            className: 'hidden @min-[40rem]/alert-groups:table-cell',
            render: (_, alert) => <OptionalTimeLabel time={alert.snooze_until} fallback="Not snoozed" />,
        },
    ]
    if (canSnoozeGroups) {
        columns.push({
            key: 'actions',
            width: 0,
            render: (_, alert) => <PlatformAlertGroupSnoozeMenu alert={alert} />,
        })
    }

    return (
        <div className="@container/alert-groups">
            <LemonTable
                dataSource={[...alerts]}
                columns={columns}
                rowKey="id"
                emptyState="No checks have run for this alert yet."
            />
        </div>
    )
}
