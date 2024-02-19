import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconEllipsis } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { ActionType, HookConfigType } from '~/types'

import { actionWebhooksLogic } from './actionWebhooksLogic'

function EditActionWebhookModal({ actionId }: { actionId: ActionType['id'] }): JSX.Element {
    const logic = actionWebhooksLogic({ id: actionId })
    const { editingWebhookId, editingWebhookChanged, isEditingWebhookSubmitting } = useValues(logic)
    const { setEditingWebhookId, submitEditingWebhook } = useActions(logic)

    const isNew = editingWebhookId === 'new'

    return (
        <Form logic={actionWebhooksLogic} props={{ id: actionId }} formKey="editingWebhook">
            <LemonModal
                title={`${isNew ? 'Create' : 'Edit'} webhook configuration`}
                onClose={() => setEditingWebhookId(null)}
                isOpen={!!editingWebhookId}
                width="40rem"
                hasUnsavedInput={editingWebhookChanged}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setEditingWebhookId(null)}>
                            Cancel
                        </LemonButton>

                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isEditingWebhookSubmitting}
                            disabled={!editingWebhookChanged}
                            onClick={() => submitEditingWebhook()}
                        >
                            {isNew ? 'Create webhook' : 'Save webhook'}
                        </LemonButton>
                    </>
                }
            >
                <>
                    <LemonField name="target" label="Target URL">
                        <LemonInput placeholder="e.g. https://hooks.slack.com/services/123/456/ABC" />
                    </LemonField>
                </>
            </LemonModal>
        </Form>
    )
}

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
            <EditActionWebhookModal actionId={actionId} />
        </div>
    )
}
