import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { WebhookInfo } from '~/types'

import {
    WebhookRefreshButton,
    WebhookSetupForm,
    WebhookStatusTags,
    WebhookUrlDisplay,
} from '../../external/forms/WebhookSetupForm'
import { webhookTabLogic } from './webhookTabLogic'

export function WebhookTab({ id }: { id: string }): JSX.Element {
    const {
        webhookInfo,
        webhookInfoLoading,
        webhookCreating,
        createWebhookResult,
        internalStateLabel,
        externalStateLabel,
        mappedTables,
        source,
        sourceConfig,
    } = useValues(webhookTabLogic({ id }))
    const { createWebhook, loadWebhookInfo } = useActions(webhookTabLogic({ id }))

    if (webhookInfoLoading && !webhookInfo) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="w-1/3 h-6" />
                <LemonSkeleton className="w-full h-20" />
                <LemonSkeleton className="w-full h-32" />
            </div>
        )
    }

    // No webhook exists yet — show setup flow (or re-creation if external webhook is missing)
    const logicProps = { id }

    if (!webhookInfo?.exists) {
        return (
            <WebhookSetupForm
                sourceName={sourceConfig?.label ?? source?.source_type ?? 'source'}
                sourceConfig={sourceConfig}
                webhookResult={createWebhookResult}
                webhookCreating={webhookCreating}
                onCreateWebhook={createWebhook}
                formLogic={webhookTabLogic(logicProps)}
                formKey="webhookFieldInputs"
            />
        )
    }

    // Webhook exists but is missing at the source — offer re-creation
    const externalMissing =
        webhookInfo.external_status && !webhookInfo.external_status.exists && !webhookInfo.external_status.error

    return (
        <div className="space-y-4">
            <WebhookStatusSection
                webhookInfo={webhookInfo}
                webhookInfoLoading={webhookInfoLoading}
                internalStateLabel={internalStateLabel}
                externalStateLabel={externalStateLabel}
                onRefresh={loadWebhookInfo}
            />
            {externalMissing && (
                <WebhookRecreateSection
                    id={id}
                    sourceName={sourceConfig?.label ?? source?.source_type ?? 'source'}
                    sourceConfig={sourceConfig}
                    webhookCreating={webhookCreating}
                    createWebhookResult={createWebhookResult}
                    onCreateWebhook={createWebhook}
                />
            )}
            <WebhookDetailsSection webhookInfo={webhookInfo} />
            {mappedTables.length > 0 && <MappedTablesSection mappedTables={mappedTables} />}
        </div>
    )
}

function WebhookStatusSection({
    webhookInfo,
    webhookInfoLoading,
    internalStateLabel,
    externalStateLabel,
    onRefresh,
}: {
    webhookInfo: WebhookInfo
    webhookInfoLoading: boolean
    internalStateLabel: { label: string; tagType: 'success' | 'warning' | 'danger' | 'default' }
    externalStateLabel: { label: string; tagType: 'success' | 'warning' | 'danger' | 'default' }
    onRefresh: () => void
}): JSX.Element {
    const externalStatus = webhookInfo.external_status

    return (
        <LemonCard hoverEffect={false} className="space-y-4">
            <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold mb-0">Webhook status</h3>
                <WebhookRefreshButton onClick={onRefresh} loading={webhookInfoLoading} />
            </div>

            <WebhookStatusTags externalStateLabel={externalStateLabel} internalStateLabel={internalStateLabel} />

            {externalStatus && !externalStatus.exists && !externalStatus.error && (
                <LemonBanner type="warning">
                    Webhook not found on your source account. It may have been deleted. You can re-create it below.
                </LemonBanner>
            )}
            {externalStatus?.error && <LemonBanner type="info">{externalStatus.error}</LemonBanner>}
        </LemonCard>
    )
}

function WebhookRecreateSection({
    id,
    sourceName,
    sourceConfig,
    webhookCreating,
    createWebhookResult,
    onCreateWebhook,
}: {
    id: string
    sourceName: string
    sourceConfig: any
    webhookCreating: boolean
    createWebhookResult: { success: boolean; webhook_url: string; error?: string } | null
    onCreateWebhook: () => void
}): JSX.Element {
    return (
        <WebhookSetupForm
            sourceName={sourceName}
            sourceConfig={sourceConfig}
            webhookResult={createWebhookResult}
            webhookCreating={webhookCreating}
            onCreateWebhook={onCreateWebhook}
            formLogic={webhookTabLogic({ id })}
            formKey="webhookFieldInputs"
        />
    )
}

function WebhookDetailsSection({ webhookInfo }: { webhookInfo: WebhookInfo }): JSX.Element {
    const externalStatus = webhookInfo.external_status

    return (
        <LemonCard hoverEffect={false} className="space-y-3">
            <h3 className="text-lg font-semibold">Details</h3>

            {webhookInfo.webhook_url && <WebhookUrlDisplay url={webhookInfo.webhook_url} />}

            {externalStatus?.enabled_events && externalStatus.enabled_events.length > 0 && (
                <div>
                    <p className="text-xs font-semibold text-muted uppercase mb-1">
                        Listening to {externalStatus.enabled_events.length} event
                        {externalStatus.enabled_events.length !== 1 ? 's' : ''}
                    </p>
                    <div className="flex flex-wrap gap-1 mt-1">
                        {externalStatus.enabled_events.map((event) => (
                            <LemonTag key={event} type="muted" className="text-xs">
                                {event}
                            </LemonTag>
                        ))}
                    </div>
                </div>
            )}
        </LemonCard>
    )
}

function MappedTablesSection({
    mappedTables,
}: {
    mappedTables: { objectType: string; tableName: string }[]
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="space-y-3">
            <h3 className="text-lg font-semibold">Mapped tables</h3>
            <LemonTable
                dataSource={mappedTables}
                columns={[
                    {
                        title: 'Object type',
                        dataIndex: 'objectType',
                        key: 'objectType',
                    },
                    {
                        title: 'Table',
                        dataIndex: 'tableName',
                        key: 'tableName',
                    },
                ]}
                size="small"
            />
        </LemonCard>
    )
}
