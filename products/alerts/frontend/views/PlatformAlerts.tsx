import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import {
    BillingAlertConfigurationStateEnumApi,
    PlatformAlertApi,
    PlatformAlertConfigurationApi,
} from '../generated/api.schemas'
import { platformAlertsLogic } from '../logic/platformAlertsLogic'

const STATE_TAGS: Record<BillingAlertConfigurationStateEnumApi, { label: string; type: LemonTagType }> = {
    [BillingAlertConfigurationStateEnumApi.NotFiring]: { label: 'Not firing', type: 'default' },
    [BillingAlertConfigurationStateEnumApi.Firing]: { label: 'Firing', type: 'danger' },
    [BillingAlertConfigurationStateEnumApi.Errored]: { label: 'Errored', type: 'danger' },
    [BillingAlertConfigurationStateEnumApi.Snoozed]: { label: 'Snoozed', type: 'muted' },
    [BillingAlertConfigurationStateEnumApi.Broken]: { label: 'Broken', type: 'danger' },
}

function OptionalTime({ time, fallback }: { time: string | null; fallback: string }): JSX.Element {
    return time ? <TZLabel time={time} /> : <span className="text-muted text-xs">{fallback}</span>
}

const GROUP_COLUMNS: LemonTableColumns<PlatformAlertApi> = [
    {
        title: 'Group',
        dataIndex: 'grouping_key',
        render: (_, alert) => alert.grouping_key || <span className="text-muted">Ungrouped</span>,
    },
    {
        title: 'State',
        dataIndex: 'state',
        render: (_, alert) => {
            const tag = STATE_TAGS[alert.state] ?? { label: alert.state, type: 'default' }
            return (
                <LemonTag type={tag.type} data-attr={`platform-alert-state-${alert.state}`}>
                    {tag.label}
                </LemonTag>
            )
        },
    },
    {
        title: 'Firing since',
        dataIndex: 'firing_started_at',
        render: (_, alert) => <OptionalTime time={alert.firing_started_at} fallback="Not firing" />,
    },
    {
        title: 'Last notified',
        dataIndex: 'last_notified_at',
        render: (_, alert) => <OptionalTime time={alert.last_notified_at} fallback="Never" />,
    },
]

const CONFIGURATION_COLUMNS: LemonTableColumns<PlatformAlertConfigurationApi> = [
    { title: 'Name', dataIndex: 'name' },
    {
        title: 'Source',
        dataIndex: 'source_kind',
        render: (_, configuration) => <LemonTag>{configuration.source_kind}</LemonTag>,
    },
    {
        title: 'Enabled',
        dataIndex: 'enabled',
        render: (_, configuration) =>
            configuration.enabled ? <LemonTag type="success">Yes</LemonTag> : <LemonTag type="muted">No</LemonTag>,
    },
    {
        title: 'Next check',
        dataIndex: 'next_check_at',
        render: (_, configuration) => <OptionalTime time={configuration.next_check_at} fallback="Pending" />,
    },
    {
        title: 'Failed checks in a row',
        dataIndex: 'consecutive_failures',
    },
    {
        title: 'Groups',
        render: (_, configuration) => configuration.alerts.length,
    },
]

export function PlatformAlerts(): JSX.Element {
    const { platformAlerts, platformAlertsLoading, platformAlertsLoadFailed } = useValues(platformAlertsLogic)
    const { loadPlatformAlerts } = useActions(platformAlertsLogic)

    if (platformAlertsLoadFailed) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => loadPlatformAlerts(),
                    'data-attr': 'platform-alerts-retry',
                }}
            >
                Platform alerts could not be loaded.
            </LemonBanner>
        )
    }

    return (
        <LemonTable
            dataSource={platformAlerts ?? []}
            columns={CONFIGURATION_COLUMNS}
            loading={platformAlerts === null || platformAlertsLoading}
            rowKey="id"
            emptyState="No platform alerts in this project yet."
            data-attr="platform-alerts-table"
            expandable={{
                rowExpandable: (configuration) => configuration.alerts.length > 0,
                expandedRowRender: (configuration) => (
                    <LemonTable
                        dataSource={[...configuration.alerts]}
                        columns={GROUP_COLUMNS}
                        rowKey="id"
                        size="small"
                        embedded
                    />
                ),
            }}
            footer={
                <div className="flex justify-end p-2">
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => loadPlatformAlerts()}
                        loading={platformAlertsLoading}
                        data-attr="platform-alerts-refresh"
                    >
                        Refresh
                    </LemonButton>
                </div>
            }
        />
    )
}
