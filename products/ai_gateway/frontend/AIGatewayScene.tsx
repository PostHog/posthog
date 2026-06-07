import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl } from 'kea-router'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonMenu,
    LemonModal,
    LemonTable,
    LemonTableColumns,
    Spinner,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { aiGatewayLogic, CredentialType } from './aiGatewayLogic'
import { GatewayApi, UserBasicApi } from './generated/api.schemas'

// The generated UserBasicApi isn't structurally assignable to ProfilePicture's
// user prop (its hedgehog_config type differs), so narrow to the fields it reads.
const profileUser = (user: UserBasicApi | null): { first_name?: string; last_name?: string; email?: string } => ({
    first_name: user?.first_name,
    last_name: user?.last_name,
    email: user?.email,
})

// Deep-link to the personal API key settings, opening the create modal pre-filled
// with the llm_gateway:read scope (the `preset` param is read by personalAPIKeysLogic).
const CREATE_KEY_URL = combineUrl(urls.settings('user-api-keys'), { preset: 'llm_gateway' }).url

export const scene: SceneExport = {
    component: AIGatewayScene,
    logic: aiGatewayLogic,
    productKey: ProductKey.AI_GATEWAY,
}

export function AIGatewayScene(): JSX.Element {
    const { gateways, gatewaysLoading } = useValues(aiGatewayLogic)
    const { openNewGateway, openEditGateway, deleteGateway, loadCredentials } = useActions(aiGatewayLogic)

    const columns: LemonTableColumns<GatewayApi> = [
        {
            title: 'Slug',
            dataIndex: 'slug',
            render: (slug) => <span className="font-mono">{slug as string}</span>,
        },
        {
            title: 'Credentials',
            dataIndex: 'bound_credentials_count',
            render: (count) => `${count ?? 0}`,
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: (_, gateway) =>
                gateway.created_by ? (
                    <div className="flex items-center gap-2">
                        <ProfilePicture user={profileUser(gateway.created_by)} size="md" />
                        <span>{gateway.created_by.first_name || gateway.created_by.email}</span>
                    </div>
                ) : (
                    <span className="text-secondary">—</span>
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
                                    gateway.bound_credentials_count > 0
                                        ? `${gateway.bound_credentials_count} credential(s) attribute usage to this gateway. They'll lose attribution and stop working until reassigned. This cannot be undone.`
                                        : 'This cannot be undone.',
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
                expandable={{
                    onRowExpand: (gateway) => loadCredentials({ gatewayId: gateway.id }),
                    expandedRowRender: (gateway) => <GatewayCredentials gateway={gateway} />,
                }}
            />
            <EditGatewayModal />
        </SceneContent>
    )
}

function GatewayCredentials({ gateway }: { gateway: GatewayApi }): JSX.Element {
    const { gateways, credentialsByGateway, credentialsByGatewayLoading } = useValues(aiGatewayLogic)
    const { moveCredential } = useActions(aiGatewayLogic)

    const credentials = credentialsByGateway[gateway.id]
    const otherGateways = gateways.filter((g) => g.id !== gateway.id)

    if (!credentials) {
        return (
            <div className="px-4 py-2">
                <Spinner /> Loading credentials…
            </div>
        )
    }

    const moveMenu = (credentialType: CredentialType, credentialId: string): JSX.Element => (
        <LemonMenu
            items={otherGateways.map((g) => ({
                label: g.slug,
                onClick: () =>
                    moveCredential({ credentialType, credentialId, fromGatewayId: gateway.id, toGatewayId: g.id }),
            }))}
        >
            <LemonButton
                size="small"
                type="secondary"
                disabledReason={!otherGateways.length ? 'No other gateways' : undefined}
            >
                Move to…
            </LemonButton>
        </LemonMenu>
    )

    if (!credentials.personal_api_keys.length && !credentials.oauth_applications.length) {
        return (
            <div className="flex items-center gap-3 px-4 py-2">
                <span className="text-secondary">No credentials attribute usage to this gateway yet.</span>
                <LemonButton type="secondary" size="small" icon={<IconPlus />} to={CREATE_KEY_URL}>
                    Create personal API key
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-1 px-4 py-2">
            {credentials.personal_api_keys.map((key) => (
                <div key={key.id} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <ProfilePicture user={profileUser(key.user)} size="sm" />
                        <span>{key.label}</span>
                        <span className="text-secondary">personal API key</span>
                    </div>
                    {moveMenu('personal_api_key', key.id)}
                </div>
            ))}
            {credentials.oauth_applications.map((app) => (
                <div key={app.id} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <span>{app.name}</span>
                        <span className="text-secondary">OAuth app · {app.client_id}</span>
                    </div>
                    {moveMenu('oauth_application', app.id)}
                </div>
            ))}
            {credentialsByGatewayLoading && <Spinner />}
        </div>
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
