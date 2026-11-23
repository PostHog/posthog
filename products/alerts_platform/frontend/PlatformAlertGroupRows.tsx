import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { PlatformAlertApi, PlatformAlertConfigurationApi } from './generated/api.schemas'
import { OptionalTimeLabel } from './OptionalTimeLabel'
import { PlatformAlertGroupCell } from './PlatformAlertGroupCell'
import { PlatformAlertStateLabel } from './PlatformAlertStateLabel'

export function PlatformAlertGroupRows({
    configuration,
}: {
    configuration: PlatformAlertConfigurationApi
}): JSX.Element {
    const columns: LemonTableColumns<PlatformAlertApi> = [
        {
            title: 'Group',
            dataIndex: 'grouping_key',
            render: (_, alert) => (
                <PlatformAlertGroupCell alert={alert} groupingKeys={configuration.grouping.keys ?? []} />
            ),
        },
        {
            title: 'State',
            dataIndex: 'state',
            render: (_, alert) => <PlatformAlertStateLabel status={alert.state} />,
        },
        {
            title: 'Firing since',
            render: (_, alert) => <OptionalTimeLabel time={alert.firing_started_at} fallback="Not firing" />,
        },
    ]
    return (
        <div className="@container/alert-groups">
            <LemonTable dataSource={[...configuration.alerts]} columns={columns} rowKey="id" embedded size="small" />
        </div>
    )
}
