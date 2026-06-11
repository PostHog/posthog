import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCopy } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { SourceConfig, SourceFieldConfig } from '~/queries/schema/schema-general'
import { WebhookInfo } from '~/types'

import { sourceFieldToElement } from '../../../shared/components/forms/SourceForm'
import {
    WebhookRefreshButton,
    WebhookSetupForm,
    WebhookStatusTags,
    WebhookUrlDisplay,
} from '../../../shared/components/forms/WebhookSetupForm'
import type { WebhookCreateResult } from '../../../shared/components/forms/WebhookSetupForm'
import { WebhookLogsSection } from './WebhookLogsSection'
import { WEBHOOK_SECTIONS, WebhookSection, webhookTabLogic } from './webhookTabLogic'

const SECTION_LABELS: Record<WebhookSection, string> = {
    overview: 'Overview',
    configuration: 'Configuration',
    activity: 'Activity',
}

const WEBHOOK_METRIC_KEYS = ['succeeded', 'failed'] as const

const WEBHOOK_METRICS_INFO: Record<string, { name: string; description: string; color: string }> = {
    succeeded: {
        name: 'Received',
        description: 'Total number of webhook events received and processed successfully',
        color: getColorVar('success'),
    },
    failed: {
        name: 'Failed',
        description: 'Total number of webhook events that had errors during processing',
        color: getColorVar('danger'),
    },
}

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
        canDeleteWebhook,
        webhookDeleting,
        currentSection,
    } = useValues(webhookTabLogic({ id }))
    const { createWebhook, loadWebhookInfo, deleteWebhook, setCurrentSection } = useActions(webhookTabLogic({ id }))

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

    const hogFunctionId = webhookInfo.hog_function?.id
    const hasConfiguration = !!sourceConfig && (sourceConfig.webhookFields?.length ?? 0) > 0
    const visibleSections = WEBHOOK_SECTIONS.filter(
        (key) => (key !== 'configuration' || hasConfiguration) && (key !== 'activity' || !!hogFunctionId)
    )
    const activeSection = visibleSections.includes(currentSection) ? currentSection : 'overview'

    let body: JSX.Element
    switch (activeSection) {
        case 'configuration':
            body = <WebhookConfigurationSection sourceConfig={sourceConfig!} formLogicProps={logicProps} />
            break
        case 'activity':
            body = (
                <>
                    {hogFunctionId && <WebhookMetricsSection hogFunctionId={hogFunctionId} />}
                    {hogFunctionId && <WebhookLogsSection hogFunctionId={hogFunctionId} />}
                </>
            )
            break
        default:
            body = (
                <>
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
                    {!externalMissing && (webhookInfo.missing_events?.length ?? 0) > 0 && (
                        <WebhookMissingEventsSection
                            missingEvents={webhookInfo.missing_events!}
                            sourceName={sourceConfig?.label ?? source?.source_type ?? 'source'}
                        />
                    )}
                    <WebhookDetailsSection webhookInfo={webhookInfo} />
                    {mappedTables.length > 0 && <MappedTablesSection mappedTables={mappedTables} />}
                    <WebhookDeleteSection
                        canDelete={canDeleteWebhook}
                        deleting={webhookDeleting}
                        onDelete={deleteWebhook}
                    />
                </>
            )
    }

    return (
        <WebhookSectionLayout
            sections={visibleSections}
            section={activeSection}
            onSectionChange={setCurrentSection}
            body={body}
        />
    )
}

function WebhookSectionLayout({
    sections,
    section,
    onSectionChange,
    body,
}: {
    sections: readonly WebhookSection[]
    section: WebhookSection
    onSectionChange: (section: WebhookSection) => void
    body: JSX.Element
}): JSX.Element {
    return (
        <div className="flex items-start gap-6">
            <nav className="sticky top-[var(--scene-title-section-height,50px)] flex flex-col w-56 flex-shrink-0">
                <ul className="flex flex-col gap-y-px">
                    {sections.map((key) => (
                        <li key={key}>
                            <LemonButton
                                fullWidth
                                size="small"
                                active={section === key}
                                onClick={() => onSectionChange(key)}
                                data-attr={`webhook-section-${key}`}
                            >
                                {SECTION_LABELS[key]}
                            </LemonButton>
                        </li>
                    ))}
                </ul>
            </nav>
            <div className="flex-1 min-w-0 space-y-4">{body}</div>
        </div>
    )
}

function WebhookConfigurationSection({
    sourceConfig,
    formLogicProps,
}: {
    sourceConfig: SourceConfig
    formLogicProps: { id: string }
}): JSX.Element {
    const { webhookFieldInputs, isWebhookFieldInputsSubmitting } = useValues(webhookTabLogic(formLogicProps))
    const webhookFields = sourceConfig.webhookFields ?? []

    return (
        <LemonCard hoverEffect={false} className="space-y-3">
            <h3 className="text-lg font-semibold">Configuration</h3>
            <Form logic={webhookTabLogic} props={formLogicProps} formKey="webhookFieldInputs" enableFormOnSubmit>
                <div className="space-y-3 ph-no-capture">
                    {webhookFields.map((field: SourceFieldConfig) =>
                        sourceFieldToElement(field, sourceConfig, webhookFieldInputs[field.name], true)
                    )}
                    <LemonButton type="primary" htmlType="submit" loading={isWebhookFieldInputsSubmitting}>
                        Save changes
                    </LemonButton>
                </div>
            </Form>
        </LemonCard>
    )
}

function WebhookMetricsSection({ hogFunctionId }: { hogFunctionId: string }): JSX.Element {
    const logicKey = `webhook-metrics-${hogFunctionId}`
    const logic = appMetricsLogic({
        logicKey,
        loadOnMount: true,
        loadOnChanges: true,
        forceParams: {
            appSource: 'hog_function',
            appSourceId: hogFunctionId,
            metricName: [...WEBHOOK_METRIC_KEYS],
            breakdownBy: 'metric_name',
        },
    })

    const { appMetricsTrendsLoading, getSingleTrendSeries } = useValues(logic)

    return (
        <LemonCard hoverEffect={false} className="space-y-4">
            <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold mb-0">Metrics</h3>
                <AppMetricsFilters logicKey={logicKey} />
            </div>

            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {WEBHOOK_METRIC_KEYS.map((key) => (
                    <AppMetricSummary
                        key={key}
                        name={WEBHOOK_METRICS_INFO[key].name}
                        description={WEBHOOK_METRICS_INFO[key].description}
                        loading={appMetricsTrendsLoading}
                        timeSeries={getSingleTrendSeries(key)}
                        previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                        color={WEBHOOK_METRICS_INFO[key].color}
                        colorIfZero={getColorVar('muted')}
                        hideIfZero={!['succeeded', 'failed'].includes(key)}
                    />
                ))}
            </div>
        </LemonCard>
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
    createWebhookResult: WebhookCreateResult | null
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

function WebhookMissingEventsSection({
    missingEvents,
    sourceName,
}: {
    missingEvents: string[]
    sourceName: string
}): JSX.Element {
    return (
        <LemonBanner
            type="warning"
            action={{
                icon: <IconCopy />,
                children: 'Copy events',
                onClick: () => void copyToClipboard(missingEvents.join('\n'), 'webhook events'),
            }}
        >
            <p className="mb-2">
                Some tables won't receive data until these events are added to your {sourceName} webhook. This happens
                when the webhook was created manually, or before a newly added table was supported. Add them in your{' '}
                {sourceName} dashboard, then refresh.
            </p>
            <div className="flex flex-wrap gap-1">
                {missingEvents.map((event) => (
                    <LemonTag key={event} type="warning" className="text-xs">
                        {event}
                    </LemonTag>
                ))}
            </div>
        </LemonBanner>
    )
}

function WebhookDetailsSection({ webhookInfo }: { webhookInfo: WebhookInfo }): JSX.Element {
    const externalStatus = webhookInfo.external_status

    return (
        <LemonCard hoverEffect={false} className="space-y-3">
            <h3 className="text-lg font-semibold">Details</h3>

            {webhookInfo.webhook_url && <WebhookUrlDisplay url={webhookInfo.webhook_url} />}

            {externalStatus?.enabled_events && externalStatus.enabled_events.length > 0 && (
                <LemonCollapse
                    size="small"
                    panels={[
                        {
                            key: 'enabled-events',
                            header: `Listening to ${externalStatus.enabled_events.length} event${
                                externalStatus.enabled_events.length !== 1 ? 's' : ''
                            }`,
                            content: (
                                <div className="flex flex-wrap gap-1">
                                    {externalStatus.enabled_events.map((event) => (
                                        <LemonTag key={event} type="muted" className="text-xs">
                                            {event}
                                        </LemonTag>
                                    ))}
                                </div>
                            ),
                        },
                    ]}
                />
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

function WebhookDeleteSection({
    canDelete,
    deleting,
    onDelete,
}: {
    canDelete: boolean
    deleting: boolean
    onDelete: () => void
}): JSX.Element {
    const handleDelete = (): void => {
        LemonDialog.open({
            title: 'Delete webhook',
            description:
                'This will delete the webhook from PostHog and attempt to remove it from the source. This action cannot be undone.',
            primaryButton: {
                children: 'Delete webhook',
                status: 'danger',
                onClick: onDelete,
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const deleteButton = (
        <LemonButton
            type="secondary"
            status="danger"
            onClick={handleDelete}
            loading={deleting}
            disabledReason={
                !canDelete ? 'Disable syncing on all webhook tables before deleting the webhook' : undefined
            }
        >
            Delete webhook
        </LemonButton>
    )

    return (
        <LemonCard hoverEffect={false} className="space-y-3">
            <h3 className="text-lg font-semibold">Danger zone</h3>
            <div className="flex items-center justify-between">
                <div>
                    <p className="mb-0">Remove the webhook from PostHog and the source.</p>
                    {!canDelete && (
                        <p className="text-muted text-xs mt-1 mb-0">
                            Tables using webhook sync mode depend on this webhook. Switch them to an alternative sync
                            mode or disable syncing first.
                        </p>
                    )}
                </div>
                {deleteButton}
            </div>
        </LemonCard>
    )
}
