import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { RobotHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { aiGatewayLogic } from './aiGatewayLogic'
import { GatewayCredentials, profileUser } from './GatewayCredentials'
import { UsageTiles } from './gatewayUsage'
import { GatewayApi } from './generated/api.schemas'

const AI_GATEWAY_DESCRIPTION =
    'One endpoint for every major LLM, billed at cost — no markup on tokens. Point your app at a gateway and PostHog ' +
    'tracks usage, cost, and spend for you, broken down by app, team, or environment. Spin up a gateway per use case ' +
    'and add or rotate keys anytime, with no downtime.'

export const scene: SceneExport = {
    component: AIGatewayScene,
    logic: aiGatewayLogic,
    productKey: ProductKey.AI_GATEWAY,
}

export function AIGatewayScene(): JSX.Element {
    const { gateways, gatewaysLoading, usage, usageLoading } = useValues(aiGatewayLogic)
    const { openNewGateway, openEditGateway, deleteGateway, loadCredentials } = useActions(aiGatewayLogic)

    const columns: LemonTableColumns<GatewayApi> = [
        {
            title: 'Slug',
            dataIndex: 'slug',
            render: (slug, gateway) => (
                <Link to={urls.aiGatewayDetail(gateway.id)} className="font-mono font-semibold">
                    {slug as string}
                </Link>
            ),
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
                description="Every major LLM through one endpoint, billed at cost."
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <LemonButton type="primary" icon={<IconPlus />} onClick={openNewGateway}>
                        New gateway
                    </LemonButton>
                }
            />
            {gateways.length ? (
                <GatewayInfoBanner onCreate={openNewGateway} />
            ) : (
                <ProductIntroduction
                    productName="AI gateway"
                    productKey={ProductKey.AI_GATEWAY}
                    thingName="gateway"
                    description={AI_GATEWAY_DESCRIPTION}
                    action={openNewGateway}
                    isEmpty
                    customHog={RobotHog}
                />
            )}
            <section className="flex flex-col gap-2">
                <h3 className="m-0">Usage · last 30 days</h3>
                <UsageTiles usage={usage} loading={usageLoading} />
            </section>
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

// Persistent (non-dismissible) intro — unlike ProductIntroduction, stays put once gateways exist so
// teammates landing on the page for the first time still get the pitch and a way in.
function GatewayInfoBanner({ onCreate }: { onCreate: () => void }): JSX.Element {
    return (
        <div className="border-2 border-dashed border-primary w-full p-6 rounded mt-2 mb-4 flex items-center gap-6">
            <RobotHog className="w-24 hidden md:block shrink-0" />
            <div className="flex-shrink">
                <h3 className="m-0">Every major LLM through one endpoint, billed at cost</h3>
                <p className="ml-0 mt-1 mb-3 text-secondary">{AI_GATEWAY_DESCRIPTION}</p>
                <LemonButton type="primary" size="small" icon={<IconPlus />} onClick={onCreate}>
                    New gateway
                </LemonButton>
            </div>
        </div>
    )
}

export function EditGatewayModal(): JSX.Element {
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
