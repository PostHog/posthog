import { useActions, useValues } from 'kea'

import { LemonSwitch, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import type { AlertReceiverApi } from '../generated/api.schemas'
import { receiverTarget, receiverTypeLabel } from './platformAlertRoutingFormat'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'

export function PlatformAlertReceiversTable(): JSX.Element {
    const { receivers, receiversLoading, togglingIds, editDisabledReason } = useValues(platformAlertRoutingLogic)
    const { openReceiverModal, deleteReceiver, setReceiverEnabled } = useActions(platformAlertRoutingLogic)

    const columns: LemonTableColumns<AlertReceiverApi> = [
        { title: 'Name', dataIndex: 'name' },
        { title: 'Type', render: (_, receiver) => receiverTypeLabel(receiver.type) },
        {
            title: 'Destination',
            render: (_, receiver) => <span className="font-mono text-xs break-all">{receiverTarget(receiver)}</span>,
        },
        { title: 'Routes', dataIndex: 'route_count' },
        {
            title: 'Enabled',
            render: (_, receiver) => (
                <LemonSwitch
                    checked={receiver.enabled}
                    onChange={(enabled) => setReceiverEnabled(receiver, enabled)}
                    disabledReason={editDisabledReason ?? (togglingIds.includes(receiver.id) ? 'Saving…' : null)}
                    data-attr="platform-alert-receiver-enabled"
                />
            ),
        },
        {
            width: 0,
            render: (_, receiver) => (
                <More
                    overlay={
                        <LemonMenuOverlay
                            items={[
                                {
                                    label: 'Edit',
                                    onClick: () => openReceiverModal(receiver),
                                    disabledReason: editDisabledReason,
                                },
                                {
                                    label: 'Delete',
                                    status: 'danger',
                                    onClick: () => deleteReceiver(receiver),
                                    disabledReason: editDisabledReason,
                                },
                            ]}
                        />
                    }
                    data-attr="platform-alert-receiver-more"
                />
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={receivers ?? []}
            columns={columns}
            loading={receiversLoading || receivers === null}
            rowKey="id"
            emptyState="No receivers yet. Add one to start routing alerts to it."
        />
    )
}
