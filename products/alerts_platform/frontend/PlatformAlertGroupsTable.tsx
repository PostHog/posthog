import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { PlatformAlertApi } from './generated/api.schemas'
import { OptionalTimeLabel } from './OptionalTimeLabel'
import { PlatformAlertStatusTag } from './PlatformAlertStatusTag'

const COLUMNS: LemonTableColumns<PlatformAlertApi> = [
    {
        title: 'Group',
        dataIndex: 'grouping_key',
        render: (_, alert) => alert.grouping_key || <span className="text-secondary">Ungrouped</span>,
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
        render: (_, alert) => <OptionalTimeLabel time={alert.last_notified_at} fallback="Never" />,
    },
    {
        title: 'Snoozed until',
        render: (_, alert) => <OptionalTimeLabel time={alert.snooze_until} fallback="Not snoozed" />,
    },
]

export function PlatformAlertGroupsTable({ alerts }: { alerts: readonly PlatformAlertApi[] }): JSX.Element {
    return (
        <LemonTable
            dataSource={[...alerts]}
            columns={COLUMNS}
            rowKey="id"
            emptyState="No checks have run for this alert yet."
        />
    )
}
