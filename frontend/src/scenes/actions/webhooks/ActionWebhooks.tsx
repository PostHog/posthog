import { IconPencil, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonTable,
    LemonTableColumns,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconEllipsis } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { ActionType, HookConfigType } from '~/types'

import { actionWebhooksLogic } from './actionWebhooksLogic'

export function ActionWebhookEdit({ actionId }: { actionId: ActionType['id'] }): JSX.Element {
    const logic = actionWebhooksLogic({ id: actionId })
    const { editingWebhookId, editingWebhookChanged, isEditingWebhookSubmitting } = useValues(logic)
    const { setEditingWebhookId, submitEditingWebhook } = useActions(logic)

    const isNew = editingWebhookId === 'new'

    return (
        <Form logic={actionWebhooksLogic} props={{ id: actionId }} formKey="editingWebhook" enableFormOnSubmit>
            <div className="space-y-2">
                <LemonField name="target" label="Target URL">
                    <LemonInput placeholder="e.g. https://hooks.slack.com/services/123/456/ABC" />
                </LemonField>

                <LemonField
                    name="format_text"
                    label="Text message format"
                    help={
                        <>
                            <p>
                                By default webhooks will receive a JSON payload containing the entire event. You can
                                override this to instead send
                            </p>
                            <Link to="https://posthog.com/docs/integrate/webhooks/message-formatting" target="_blank">
                                See documentation on how to format webhook messages.
                            </Link>
                        </>
                    }
                >
                    <LemonTextArea
                        placeholder="[action.name] triggered by [person]"
                        data-attr="edit-webhook-message-format"
                    />
                </LemonField>
            </div>
            <div className="flex items-center justify-end gap-2">
                <LemonButton type="secondary" onClick={() => setEditingWebhookId(null)}>
                    Cancel
                </LemonButton>

                <LemonButton
                    type="primary"
                    loading={isEditingWebhookSubmitting}
                    disabled={!editingWebhookChanged}
                    onClick={() => submitEditingWebhook()}
                >
                    {isNew ? 'Create webhook' : 'Save webhook'}
                </LemonButton>
            </div>
        </Form>
    )
}

export function ActionWebhooks({ actionId }: { actionId: number }): JSX.Element {
    const { actionWebhooks, editingWebhookId } = useValues(actionWebhooksLogic({ id: actionId }))
    const { deleteActionWebhook, setEditingWebhookId } = useActions(actionWebhooksLogic({ id: actionId }))

    const columns: LemonTableColumns<HookConfigType> = [
        {
            key: 'target',
            title: 'Webhook target URL',
            render: function Render(_, item): JSX.Element {
                return (
                    <Link className="font-semibold" subtle onClick={() => setEditingWebhookId(item.id)}>
                        {item.target}
                    </Link>
                )
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
                                    setEditingWebhookId(item.id)
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
            <LemonTable
                columns={columns}
                dataSource={actionWebhooks ?? []}
                expandable={{
                    rowExpandable: () => true,
                    expandedRowRender: () => {
                        return (
                            <div className="p-4">
                                <ActionWebhookEdit actionId={actionId} />
                            </div>
                        )
                    },
                    isRowExpanded: (record) => record.id === editingWebhookId,
                    onRowExpand: (record) => setEditingWebhookId(record.id),
                    onRowCollapse: () => setEditingWebhookId(null),
                }}
            />
        </div>
    )
}
