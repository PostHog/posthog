import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconEllipsis } from 'lib/lemon-ui/icons'

import { HookConfigType } from '~/types'

import { actionWebhooksLogic } from './actionWebhooksLogic'

export function ActionWebhooks({ actionId }: { actionId: number }): JSX.Element {
    const { actionWebhooks } = useValues(actionWebhooksLogic({ id: actionId }))
    const { deleteActionWebhook } = useActions(actionWebhooksLogic({ id: actionId }))

    const columns: LemonTableColumns<HookConfigType> = [
        {
            key: 'target',
            title: 'Webhook target URL',
            render: function Render(_, item): JSX.Element {
                return <div className="">{item.target}</div>
            },
            sorter: (a, b) => String(a[0]).localeCompare(String(b[0])),
        },
        {
            key: 'format_text',
            title: 'Message format',
            render: function Render(_, item): JSX.Element {
                return item.format_text ? (
                    <code>{item.format_text}</code>
                ) : (
                    <span className="text-muted italic">Default JSON payload</span>
                )
            },
        },

        {
            key: 'actions',
            title: '',
            width: 0,
            render: function Render(_, item): JSX.Element {
                return (
                    <LemonMenu
                        items={[
                            {
                                label: 'Edit',
                                icon: <IconPencil />,
                                onClick: () => {
                                    alert('TODO!')
                                },
                            },
                            {
                                label: 'Delete',
                                icon: <IconTrash />,
                                status: 'danger',
                                onClick: () => {
                                    deleteActionWebhook(item)
                                },
                            },
                        ]}
                    >
                        <LemonButton aria-label="more" icon={<IconEllipsis />} size="small" />
                    </LemonMenu>
                )
            },
        },
    ]
    return (
        <div className="">
            <LemonTable columns={columns} dataSource={actionWebhooks ?? []} />
        </div>
    )
}
