import { useActions, useValues } from 'kea'

import { IconBell, IconPlay, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import type { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import { destinationLabel, metricLabel, stateLabel, stateTagType, thresholdDescription } from './billingAlertDisplay'
import { billingAlertsLogic } from './billingAlertsLogic'
import type { BillingAlertConfigurationApi } from './generated/api.schemas'

export function BillingAlertsList(): JSX.Element {
    const { alerts, alertsPage, alertsPageLoading, checkingAlertId, deletingAlertIds } = useValues(billingAlertsLogic)
    const { createAlert, editAlert, checkNow, deleteAlert, loadMoreAlerts } = useActions(billingAlertsLogic)
    const columns: LemonTableColumns<BillingAlertConfigurationApi> = [
        {
            title: 'Alert',
            render: (_, alert) => (
                <LemonTableLink
                    title={alert.name}
                    description={`${metricLabel(alert.metric)} · ${thresholdDescription(alert)}`}
                    onClick={() => editAlert(alert)}
                />
            ),
        },
        {
            title: 'Destinations',
            render: (_, alert) =>
                alert.destinations.length > 0 ? (
                    <div className="flex gap-1 flex-wrap">
                        {alert.destinations.map((destination) => (
                            <LemonTag key={destination.type} size="small">
                                {destinationLabel(destination.type)}
                            </LemonTag>
                        ))}
                    </div>
                ) : (
                    'None'
                ),
        },
        {
            title: 'Last checked',
            render: (_, alert) => (alert.last_checked_at ? dayjs(alert.last_checked_at).fromNow() : 'Never'),
        },
        {
            title: 'Status',
            render: (_, alert) => <LemonTag type={stateTagType(alert)}>{stateLabel(alert)}</LemonTag>,
        },
        {
            width: 0,
            render: (_, alert) => (
                <More
                    overlay={
                        <LemonMenuOverlay
                            items={[
                                { label: 'Edit', onClick: () => editAlert(alert) },
                                {
                                    label: 'Check now',
                                    icon: <IconPlay />,
                                    disabledReason: checkingAlertId
                                        ? checkingAlertId === alert.id
                                            ? 'Check in progress.'
                                            : 'Another alert is checking.'
                                        : undefined,
                                    onClick: () => checkNow(alert),
                                },
                                {
                                    label: 'Delete',
                                    status: 'danger',
                                    disabledReason: deletingAlertIds.has(alert.id) ? 'Deleting.' : undefined,
                                    onClick: () =>
                                        LemonDialog.open({
                                            title: 'Delete billing alert?',
                                            description: `This deletes “${alert.name}” and its notification destinations.`,
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => deleteAlert(alert),
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        }),
                                },
                            ]}
                        />
                    }
                />
            ),
        },
    ]

    return (
        <div className="space-y-4" data-attr="billing-alerts-view">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <h2 className="m-0 flex items-center gap-2">
                        <IconBell /> Billing alerts
                    </h2>
                    <p className="text-secondary mb-0 mt-1">
                        Get notified when organization spend crosses a threshold.
                    </p>
                </div>
                <LemonButton type="primary" icon={<IconPlus />} onClick={createAlert} data-attr="new-billing-alert">
                    New alert
                </LemonButton>
            </div>
            <LemonTable
                dataSource={alerts}
                columns={columns}
                rowKey="id"
                loading={alertsPageLoading}
                nouns={['billing alert', 'billing alerts']}
                emptyState="No billing alerts yet."
                data-attr="billing-alerts-table"
            />
            {alertsPage.next ? (
                <div className="flex justify-center">
                    <LemonButton type="secondary" loading={alertsPageLoading} onClick={loadMoreAlerts}>
                        Load more alerts
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
