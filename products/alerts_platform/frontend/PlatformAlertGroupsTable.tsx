import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PlatformAlertApi } from './generated/api.schemas'
import { OptionalTimeLabel } from './OptionalTimeLabel'
import { groupLabels } from './platformAlertFormat'
import { PlatformAlertGroupSnoozeMenu } from './PlatformAlertGroupSnoozeMenu'
import { platformAlertLogic } from './platformAlertLogic'
import { PlatformAlertStatusTag } from './PlatformAlertStatusTag'

function GroupCell({ alert, groupingKeys }: { alert: PlatformAlertApi; groupingKeys: readonly string[] }): JSX.Element {
    if (!alert.grouping_key) {
        return <span className="text-secondary">Ungrouped</span>
    }
    const labels = groupLabels(alert, groupingKeys)
    if (!labels.length) {
        return <span className="break-all">{alert.grouping_key}</span>
    }
    return (
        <Tooltip title={`Group key: ${alert.grouping_key}`}>
            {/* An auto-layout table sizes a column to its widest unbreakable content, so a long label
                pushes the snooze action off screen. A container-relative cap lets the tag truncate. */}
            <div className="flex flex-wrap gap-1 max-w-[35cqw]" translate="no">
                {labels.map(({ key, name, value }) => (
                    <LemonTag key={key} type="muted" className="max-w-full">
                        <span className="truncate">
                            {name}: {value}
                        </span>
                    </LemonTag>
                ))}
            </div>
        </Tooltip>
    )
}

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
            render: (_, alert) => <GroupCell alert={alert} groupingKeys={groupingKeys} />,
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
