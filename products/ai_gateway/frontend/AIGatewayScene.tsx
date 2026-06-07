import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { aiGatewayLogic } from './aiGatewayLogic'
import { GatewayApi } from './generated/api.schemas'

export const scene: SceneExport = {
    component: AIGatewayScene,
    logic: aiGatewayLogic,
    productKey: ProductKey.AI_GATEWAY,
}

export function AIGatewayScene(): JSX.Element {
    const { gateways, gatewaysLoading } = useValues(aiGatewayLogic)
    const { openNewGateway, openEditGateway, deleteGateway } = useActions(aiGatewayLogic)

    const columns: LemonTableColumns<GatewayApi> = [
        {
            title: 'Slug',
            dataIndex: 'slug',
            render: (slug) => <span className="font-mono">{slug as string}</span>,
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: (_, gateway) => (
                <div className="flex items-center gap-2">
                    <ProfilePicture user={gateway.created_by} size="md" />
                    <span>{gateway.created_by?.first_name || gateway.created_by?.email}</span>
                </div>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (createdAt) => <TZLabel time={createdAt as string} />,
        },
        {
            width: 0,
            render: (_, gateway) => (
                <div className="flex gap-1 justify-end">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Rename gateway"
                        onClick={() => openEditGateway(gateway)}
                    />
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Delete gateway"
                        onClick={() =>
                            LemonDialog.open({
                                title: `Delete gateway "${gateway.slug}"?`,
                                description:
                                    'Credentials bound to this gateway will stop attributing usage to it. This cannot be undone.',
                                primaryButton: {
                                    children: 'Delete',
                                    status: 'danger',
                                    onClick: () => deleteGateway(gateway),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                    />
                </div>
            ),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="AI gateway"
                description="Manage the gateways your LLM credentials attribute their usage and spend to. Each gateway's slug is the attribution key the LLM gateway records for every request."
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <LemonButton type="primary" icon={<IconPlus />} onClick={openNewGateway}>
                        New gateway
                    </LemonButton>
                }
            />
            <LemonTable
                columns={columns}
                dataSource={gateways}
                loading={gatewaysLoading}
                rowKey="id"
                emptyState="No gateways yet. Create one to start attributing LLM usage."
            />
            <EditGatewayModal />
        </SceneContent>
    )
}

function EditGatewayModal(): JSX.Element {
    const { editingGatewayId, isEditingGatewaySubmitting, editingGatewayChanged } = useValues(aiGatewayLogic)
    const { closeModal, submitEditingGateway } = useActions(aiGatewayLogic)

    const isNew = editingGatewayId === 'new'

    return (
        <Form logic={aiGatewayLogic} formKey="editingGateway">
            <LemonModal
                title={isNew ? 'Create gateway' : 'Rename gateway'}
                isOpen={editingGatewayId !== null}
                onClose={closeModal}
                hasUnsavedInput={editingGatewayChanged}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isEditingGatewaySubmitting}
                            onClick={() => submitEditingGateway()}
                        >
                            {isNew ? 'Create' : 'Save'}
                        </LemonButton>
                    </>
                }
            >
                <LemonField name="slug" label="Slug">
                    <LemonInput placeholder="posthog_code" autoFocus />
                </LemonField>
            </LemonModal>
        </Form>
    )
}
