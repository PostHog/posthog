import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { HookConfigType } from '~/types'

import { actionWebhooksLogic } from './actionWebhooksLogic'

export function ActionWebhooks({ actionId }: { actionId: number }): JSX.Element {
    const { actionWebhooks } = useValues(actionWebhooksLogic({ id: actionId }))

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
            render: function Render(_, item): JSX.Element {
                return <></>
            },
        },
    ]
    return (
        <div className="">
            <LemonTable columns={columns} dataSource={actionWebhooks ?? []} />
        </div>
    )
}
