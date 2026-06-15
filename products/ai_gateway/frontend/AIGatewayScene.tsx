import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { RobotHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { UserBasicType } from '~/types'

import { aiGatewayLogic } from './aiGatewayLogic'
import { UsageTiles } from './gatewayUsage'
import { GatewayApi } from './generated/api.schemas'

const AI_GATEWAY_DESCRIPTION =
    'One endpoint for every major LLM, billed at cost — no markup on tokens. Point your app at your gateway and ' +
    'PostHog tracks its usage, cost, and spend for you, per model. Any project secret key with the llm_gateway:read ' +
    'scope can call it, and you can add or rotate keys anytime with no downtime.'

// created_by comes back as the generated UserBasic shape; ProfilePicture wants UserBasicType.
function profileUser(createdBy: NonNullable<GatewayApi['created_by']>): UserBasicType {
    return createdBy as unknown as UserBasicType
}

export const scene: SceneExport = {
    component: AIGatewayScene,
    logic: aiGatewayLogic,
    productKey: ProductKey.AI_GATEWAY,
}

export function AIGatewayScene(): JSX.Element {
    const { gateways, gatewaysLoading, usage, usageLoading } = useValues(aiGatewayLogic)
    const { openEditGateway } = useActions(aiGatewayLogic)

    const columns: LemonTableColumns<GatewayApi> = [
        {
            title: 'Gateway',
            dataIndex: 'slug',
            render: (slug, gateway) => (
                <Link to={urls.aiGatewayDetail(gateway.slug)} className="font-mono font-semibold">
                    {slug as string}
                </Link>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (_, gateway) => (
                <div className="flex items-center gap-2">
                    {gateway.created_by ? (
                        <>
                            <ProfilePicture user={profileUser(gateway.created_by)} size="sm" />
                            <span>{gateway.created_by.first_name || gateway.created_by.email}</span>
                        </>
                    ) : (
                        <span className="text-secondary">System</span>
                    )}
                    <span className="text-secondary">·</span>
                    <TZLabel time={gateway.created_at} />
                </div>
            ),
        },
        {
            width: 0,
            render: (_, gateway) => (
                // Stop row-click navigation from firing when using the row actions.
                <div className="flex gap-1 justify-end" onClick={(e) => e.stopPropagation()}>
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Rename gateway"
                        onClick={() => openEditGateway(gateway)}
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
                resourceType={{ type: 'ai_gateway' }}
            />
            <GatewayInfoBanner />
            <section className="flex flex-col gap-2">
                <h3 className="m-0">Usage · last 30 days</h3>
                <UsageTiles usage={usage} loading={usageLoading} />
            </section>
            <LemonTable
                columns={columns}
                dataSource={gateways}
                loading={gatewaysLoading}
                rowKey="id"
                emptyState="No gateway provisioned for this project yet."
                onRow={(gateway) => ({
                    onClick: () => router.actions.push(urls.aiGatewayDetail(gateway.slug)),
                    className: 'cursor-pointer',
                })}
            />
            <EditGatewayModal />
        </SceneContent>
    )
}

// Persistent (non-dismissible) intro so teammates landing on the page for the first time get the pitch.
function GatewayInfoBanner(): JSX.Element {
    return (
        <div className="border-2 border-dashed border-primary w-full p-6 rounded mt-2 mb-4 flex items-center gap-6">
            <RobotHog className="w-24 hidden md:block shrink-0" />
            <div className="flex-shrink">
                <h3 className="m-0">Every major LLM through one endpoint, billed at cost</h3>
                <p className="ml-0 mt-1 mb-0 text-secondary">{AI_GATEWAY_DESCRIPTION}</p>
            </div>
        </div>
    )
}

export function EditGatewayModal(): JSX.Element {
    const { editingGatewayId, isEditingGatewaySubmitting, editingGatewayChanged } = useValues(aiGatewayLogic)
    const { closeModal, submitEditingGateway } = useActions(aiGatewayLogic)

    return (
        <Form logic={aiGatewayLogic} formKey="editingGateway">
            <LemonModal
                title="Rename gateway"
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
                            Save
                        </LemonButton>
                    </>
                }
            >
                <LemonField name="slug" label="Slug">
                    {/* The submit button lives in the portaled modal footer, outside this form's
                        DOM, so Enter wouldn't reach it — submit explicitly on Enter. */}
                    <LemonInput placeholder="posthog_code" autoFocus onPressEnter={() => submitEditingGateway()} />
                </LemonField>
            </LemonModal>
        </Form>
    )
}
