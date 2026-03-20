import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { WebhookInfo } from '~/types'

import { webhookTabLogic } from './webhookTabLogic'

export function WebhookTab({ id }: { id: string }): JSX.Element {
    const {
        webhookInfo,
        webhookInfoLoading,
        webhookCreating,
        createWebhookError,
        internalStateLabel,
        externalStateLabel,
        mappedTables,
    } = useValues(webhookTabLogic({ id }))
    const { createWebhook } = useActions(webhookTabLogic({ id }))

    if (webhookInfoLoading && !webhookInfo) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="w-1/3 h-6" />
                <LemonSkeleton className="w-full h-20" />
                <LemonSkeleton className="w-full h-32" />
            </div>
        )
    }

    if (!webhookInfo?.exists) {
        return <WebhookSetup creating={webhookCreating} error={createWebhookError} onCreate={createWebhook} />
    }

    return (
        <div className="space-y-4">
            <WebhookStatusSection
                webhookInfo={webhookInfo}
                internalStateLabel={internalStateLabel}
                externalStateLabel={externalStateLabel}
            />
            <WebhookDetailsSection webhookInfo={webhookInfo} />
            {mappedTables.length > 0 && <MappedTablesSection mappedTables={mappedTables} />}
        </div>
    )
}

function WebhookSetup({
    creating,
    error,
    onCreate,
}: {
    creating: boolean
    error: string | null
    onCreate: () => void
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="space-y-4">
            <h3 className="text-lg font-semibold">Set up webhook</h3>
            <p>
                Instead of polling for changes on a schedule, a webhook pushes new data to PostHog in real-time. This
                means faster syncs and less load on your source.
            </p>
            {error && <LemonBanner type="warning">{error}</LemonBanner>}
            <LemonButton type="primary" onClick={onCreate} loading={creating}>
                {creating ? 'Creating webhook...' : 'Set up webhook'}
            </LemonButton>
        </LemonCard>
    )
}

function WebhookStatusSection({
    webhookInfo,
    internalStateLabel,
    externalStateLabel,
}: {
    webhookInfo: WebhookInfo
    internalStateLabel: { label: string; tagType: 'success' | 'warning' | 'danger' | 'default' }
    externalStateLabel: { label: string; tagType: 'success' | 'warning' | 'danger' | 'default' }
}): JSX.Element {
    const externalStatus = webhookInfo.external_status

    return (
        <LemonCard hoverEffect={false} className="space-y-4">
            <h3 className="text-lg font-semibold">Webhook status</h3>

            <div className="flex gap-8">
                <div className="space-y-1">
                    <p className="text-xs font-semibold text-muted uppercase">Source webhook</p>
                    <LemonTag type={externalStateLabel.tagType}>{externalStateLabel.label}</LemonTag>
                </div>
                <div className="space-y-1">
                    <p className="text-xs font-semibold text-muted uppercase">PostHog processing</p>
                    <LemonTag type={internalStateLabel.tagType}>{internalStateLabel.label}</LemonTag>
                </div>
            </div>

            {externalStatus && !externalStatus.exists && !externalStatus.error && (
                <LemonBanner type="warning">
                    Webhook not found on your source account. It may have been deleted.
                </LemonBanner>
            )}
            {externalStatus?.error && <LemonBanner type="info">{externalStatus.error}</LemonBanner>}
        </LemonCard>
    )
}

function WebhookDetailsSection({ webhookInfo }: { webhookInfo: WebhookInfo }): JSX.Element {
    const externalStatus = webhookInfo.external_status

    return (
        <LemonCard hoverEffect={false} className="space-y-3">
            <h3 className="text-lg font-semibold">Details</h3>

            {webhookInfo.webhook_url && (
                <div>
                    <p className="text-xs font-semibold text-muted uppercase mb-1">Webhook URL</p>
                    <div className="flex items-center gap-2">
                        <code className="text-sm bg-bg-light rounded border px-2 py-1 break-all flex-1">
                            {webhookInfo.webhook_url}
                        </code>
                        <LemonButton
                            icon={<IconCopy />}
                            size="small"
                            type="secondary"
                            onClick={() => void copyToClipboard(webhookInfo.webhook_url!, 'webhook URL')}
                        />
                    </div>
                </div>
            )}

            {webhookInfo.hog_function?.created_at && (
                <div>
                    <p className="text-xs font-semibold text-muted uppercase mb-1">Created</p>
                    <TZLabel time={webhookInfo.hog_function.created_at} />
                </div>
            )}

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
