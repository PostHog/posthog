import { useActions, useValues } from 'kea'

import { IconPencil, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import {
    PlatformAlertConfigurationApi,
    PlatformAlertConfigurationSourceKindEnumApi,
    WarehouseAlertGroupByEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'
import { configurationStatus } from 'products/alerts_platform/frontend/platformAlertFormat'
import { PlatformAlertStatusTag } from 'products/alerts_platform/frontend/PlatformAlertStatusTag'

import { alertGroupBy, emailsProjectMembers, watchedIds } from './warehouseAlertConfig'
import { WarehouseAlertModal } from './WarehouseAlertModal'
import { WarehouseAlertEntry, warehouseAlertModalLogic } from './warehouseAlertModalLogic'
import { WarehouseAlertsLogicProps, warehouseAlertsLogic } from './warehouseAlertsLogic'

export interface WarehouseAlertsSectionProps extends WarehouseAlertsLogicProps {
    /** Where the section sits, recorded on the events it sends. */
    entry: WarehouseAlertEntry
}

export function WarehouseAlertsSection({ entry, ...logicProps }: WarehouseAlertsSectionProps): JSX.Element {
    const { alerts, alertsLoading, alertsFailed, deletingAlertId, targetLabels } = useValues(
        warehouseAlertsLogic(logicProps)
    )
    const { loadAlerts, deleteAlert } = useActions(warehouseAlertsLogic(logicProps))
    const { openForCreate, openForEdit } = useActions(warehouseAlertModalLogic(logicProps))

    const isSourceAlert = logicProps.kind === PlatformAlertConfigurationSourceKindEnumApi.WarehouseSource
    const noun = isSourceAlert ? 'source' : 'destination'
    const createTargets = logicProps.targetId ? [logicProps.targetId] : []

    const describeWatches = (alert: PlatformAlertConfigurationApi): string => {
        const ids = watchedIds(alert)
        if (ids.length === 0) {
            return `All ${noun}s`
        }
        // A deleted source or destination has no label any more, so it reads as its id.
        return ids.map((id) => targetLabels[id] ?? id).join(', ')
    }

    const columns: LemonTableColumns<PlatformAlertConfigurationApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, alert) => (
                <Link
                    className="font-semibold"
                    onClick={() => openForEdit(entry, alert)}
                    data-attr="warehouse-alert-row-open"
                >
                    {alert.name}
                </Link>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, alert) => <PlatformAlertStatusTag status={configurationStatus(alert)} />,
        },
        {
            title: 'Watches',
            key: 'watches',
            render: (_, alert) => <span className="line-clamp-2">{describeWatches(alert)}</span>,
        },
        ...(isSourceAlert
            ? [
                  {
                      title: 'One alert',
                      key: 'group_by',
                      render: (_: unknown, alert: PlatformAlertConfigurationApi) =>
                          alertGroupBy(alert) === WarehouseAlertGroupByEnumApi.Schema ? 'Per table' : 'Per source',
                  },
              ]
            : []),
        {
            title: 'Emails members',
            key: 'email',
            render: (_, alert) => (emailsProjectMembers(alert) ? 'Yes' : 'No'),
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            render: (_, alert) => (
                <More
                    overlay={
                        <>
                            <LemonButton
                                fullWidth
                                icon={<IconPencil />}
                                onClick={() => openForEdit(entry, alert)}
                                data-attr="warehouse-alert-row-edit"
                            >
                                Edit
                            </LemonButton>
                            <LemonButton
                                fullWidth
                                status="danger"
                                icon={<IconTrash />}
                                onClick={() => deleteAlert(alert)}
                                disabledReason={deletingAlertId === alert.id ? 'Deleting this alert' : undefined}
                                data-attr="warehouse-alert-row-delete"
                            >
                                Delete
                            </LemonButton>
                        </>
                    }
                />
            ),
        },
    ]

    const newAlertButton = (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPlusSmall />}
            onClick={() => openForCreate(entry, createTargets)}
            data-attr="warehouse-alert-new"
        >
            New alert
        </LemonButton>
    )

    return (
        <SceneSection
            title="Alerts"
            description={
                isSourceAlert
                    ? 'Get notified by email, Slack, PagerDuty or a webhook when a source fails to sync.'
                    : 'Get notified by email, Slack, PagerDuty or a webhook when a destination fails to receive synced rows.'
            }
            actions={newAlertButton}
        >
            {alertsFailed ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadAlerts(),
                        loading: alertsLoading,
                        'data-attr': 'warehouse-alerts-retry',
                    }}
                >
                    Couldn't load alerts. Try again in a moment.
                </LemonBanner>
            ) : (
                <LemonTable
                    dataSource={alerts ?? []}
                    columns={columns}
                    loading={alertsLoading || alerts === null}
                    rowKey="id"
                    nouns={['alert', 'alerts']}
                    emptyState={
                        logicProps.targetId
                            ? `No alerts watch this ${noun} yet.`
                            : `No ${noun} alerts yet. Create one to hear about failures.`
                    }
                />
            )}
            <WarehouseAlertModal {...logicProps} />
        </SceneSection>
    )
}
