import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useCallback, useEffect } from 'react'

import { IconQuestion } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSkeleton, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { nonHogFunctionTemplatesLogic } from 'scenes/data-pipelines/utils/nonHogFunctionTemplatesLogic'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DataWarehouseInitialBillingLimitNotice } from '../DataWarehouseInitialBillingLimitNotice'
import SchemaForm from '../external/forms/SchemaForm'
import SourceForm, { sourceFieldToElement } from '../external/forms/SourceForm'
import { SyncProgressStep } from '../external/forms/SyncProgressStep'
import { FreeHistoricalSyncsBanner } from '../FreeHistoricalSyncsBanner'
import { DatawarehouseTableForm } from '../new/DataWarehouseTableForm'
import { availableSourcesDataLogic } from './availableSourcesDataLogic'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'
import { sourceWizardLogic } from './sourceWizardLogic'

export const scene: SceneExport = {
    component: NewSourceWizardScene,
    // logic: sourceWizardLogic, // NOTE: We can't mount it here as it needs the availableSourcesDataLogic to be mounted first
}

export function NewSourceWizardScene(): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesDataLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    return (
        <BindLogic logic={sourceWizardLogic} props={{ availableSources }}>
            <InternalNewSourceWizardScene />
        </BindLogic>
    )
}

function InternalNewSourceWizardScene(): JSX.Element {
    const { closeWizard } = useActions(sourceWizardLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="New data warehouse source"
                resourceType={{ type: 'data_pipeline' }}
                actions={
                    <LemonButton
                        type="secondary"
                        center
                        data-attr="source-form-cancel-button"
                        onClick={closeWizard}
                        size="small"
                    >
                        Cancel
                    </LemonButton>
                }
            />
            <InternalSourcesWizard />
        </SceneContent>
    )
}

interface NewSourcesWizardProps {
    onComplete?: () => void
    allowedSources?: ExternalDataSourceType[] // Filter to only show these source types
    initialSource?: ExternalDataSourceType // Pre-select this source and start on step 2
    hideBackButton?: boolean
}

export function NewSourcesWizard(props: NewSourcesWizardProps): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesDataLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    return (
        <BindLogic logic={sourceWizardLogic} props={{ onComplete: props.onComplete, availableSources }}>
            <InternalSourcesWizard {...props} />
        </BindLogic>
    )
}

function InternalSourcesWizard(props: NewSourcesWizardProps): JSX.Element {
    const {
        modalTitle,
        isWrapped,
        currentStep,
        isLoading,
        canGoBack,
        canGoNext,
        nextButtonText,
        selectedConnector,
        connectors,
        isSelfManagedSource,
        source,
    } = useValues(sourceWizardLogic)
    const { onBack, onSubmit, setInitialConnector } = useActions(sourceWizardLogic)
    const { tableLoading: manualLinkIsLoading } = useValues(dataWarehouseTableLogic)

    const mainContainer = useFloatingContainer()

    useEffect(() => {
        mainContainer?.scrollTo({ top: 0, behavior: 'smooth' })
    }, [currentStep, mainContainer])

    // Initialize wizard with initial source if provided
    useEffect(() => {
        if (props.initialSource && connectors.length > 0) {
            const initialConnector = connectors.find((c) => c.name === props.initialSource)
            if (initialConnector) {
                setInitialConnector(initialConnector)
            }
        }
    }, [props.initialSource]) // oxlint-disable-line react-hooks/exhaustive-deps

    const footer = useCallback(() => {
        if (currentStep === 1) {
            return null
        }

        const nextButton = (disabledReason?: string | false): JSX.Element => (
            <LemonButton
                loading={isLoading || manualLinkIsLoading}
                disabledReason={disabledReason || (!canGoNext && 'You cant click next yet')}
                type="primary"
                center
                onClick={() => onSubmit()}
                data-attr="source-link"
            >
                {nextButtonText}
            </LemonButton>
        )

        return (
            <div className="flex flex-row gap-2 justify-end mt-4">
                {!props.hideBackButton && (
                    <LemonButton
                        type="secondary"
                        center
                        data-attr="source-modal-back-button"
                        onClick={onBack}
                        disabledReason={!canGoBack && 'You cant go back from here'}
                    >
                        Back
                    </LemonButton>
                )}
                {isSelfManagedSource ? (
                    nextButton()
                ) : (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.ExternalDataSource}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        {({ disabledReason: accessDisabledReason }) => nextButton(accessDisabledReason ?? undefined)}
                    </AccessControlAction>
                )}
            </div>
        )
    }, [
        currentStep,
        canGoBack,
        onBack,
        isLoading,
        manualLinkIsLoading,
        canGoNext,
        nextButtonText,
        onSubmit,
        props.hideBackButton,
        isSelfManagedSource,
    ])

    return (
        <div>
            {!isWrapped && <DataWarehouseInitialBillingLimitNotice />}
            <>
                {selectedConnector && (
                    <div className="flex items-center gap-3 mb-4">
                        <DataWarehouseSourceIcon type={selectedConnector.name} size="small" disableTooltip />
                        <div>
                            <h4 className="text-lg font-semibold mb-0">{modalTitle}</h4>
                            <p className="text-sm text-muted-alt mb-0">
                                {source.access_method === 'direct'
                                    ? `Query ${selectedConnector.label ?? selectedConnector.name} directly from PostHog without warehouse syncs.`
                                    : `Sync data from ${selectedConnector.label ?? selectedConnector.name} into the PostHog data warehouse.`}
                            </p>
                        </div>
                    </div>
                )}

                {selectedConnector && source.access_method !== 'direct' && (
                    <FreeHistoricalSyncsBanner hideGetStarted={true} />
                )}

                {currentStep === 1 ? (
                    <FirstStep allowedSources={props.allowedSources} />
                ) : currentStep === 2 ? (
                    <SecondStep />
                ) : currentStep === 3 ? (
                    <ThirdStep />
                ) : currentStep === 4 ? (
                    <WebhookSetupStep />
                ) : currentStep === 5 ? (
                    <ProgressStep />
                ) : (
                    <div>Something went wrong...</div>
                )}

                {footer()}
            </>
        </div>
    )
}

function FirstStep({ allowedSources }: NewSourcesWizardProps): JSX.Element {
    const { availableSourcesLoading } = useValues(availableSourcesDataLogic)
    const { connectors } = useValues(sourceWizardLogic)

    // Filter out sources for onboarding flow
    const sources = connectors.reduce(
        (acc, cur) => {
            if (allowedSources) {
                if (allowedSources.indexOf(cur.name) !== -1) {
                    acc[cur.name] = cur
                }
            } else {
                acc[cur.name] = cur
            }

            return acc
        },
        {} as Record<string, SourceConfig>
    )

    const { hogFunctionTemplatesDataWarehouseSources } = useValues(
        nonHogFunctionTemplatesLogic({
            availableSources: sources ?? {},
        })
    )

    return (
        <HogFunctionTemplateList
            type="source_webhook"
            manualTemplates={hogFunctionTemplatesDataWarehouseSources}
            manualTemplatesLoading={availableSourcesLoading}
        />
    )
}

function SecondStep(): JSX.Element {
    const { selectedConnector } = useValues(sourceWizardLogic)

    return selectedConnector ? (
        <div className="space-y-4">
            {selectedConnector.caption && (
                <LemonMarkdown className="text-sm">{selectedConnector.caption}</LemonMarkdown>
            )}

            <div className="flex flex-row gap-1">
                {selectedConnector.permissionsCaption && (
                    <Tooltip
                        title={
                            <LemonMarkdown className="text-sm">{selectedConnector.permissionsCaption}</LemonMarkdown>
                        }
                        interactive
                    >
                        <LemonTag type="muted" size="small">
                            Permissions required <IconQuestion />
                        </LemonTag>
                    </Tooltip>
                )}
                {selectedConnector.permissionsCaption && selectedConnector.docsUrl && <span>&nbsp;|&nbsp;</span>}
                {selectedConnector.docsUrl && (
                    <Link to={selectedConnector.docsUrl} target="_blank">
                        View docs
                    </Link>
                )}
            </div>

            <LemonDivider />

            <SourceForm sourceConfig={selectedConnector} />
        </div>
    ) : (
        <BindLogic logic={dataWarehouseTableLogic} props={{ id: 'new' }}>
            <DatawarehouseTableForm />
        </BindLogic>
    )
}

function ThirdStep(): JSX.Element {
    return <SchemaForm />
}

function WebhookSetupStep(): JSX.Element {
    const { webhookResult, webhookCreating, selectedConnector, databaseSchema } = useValues(sourceWizardLogic)
    const { createWebhook } = useActions(sourceWizardLogic)

    const sourceName = selectedConnector?.label ?? 'source'
    const webhookTables = databaseSchema.filter(
        (s) => s.supports_webhooks && s.sync_type === 'incremental' && s.should_sync
    )

    const webhookTablesList = (
        <div className="space-y-1">
            <p className="font-semibold text-sm mb-1">Tables using webhook sync:</p>
            <ul className="list-disc list-inside text-sm">
                {webhookTables.map((t) => (
                    <li key={t.table}>{t.table}</li>
                ))}
            </ul>
        </div>
    )

    const webhookFields = selectedConnector?.webhookFields ?? []

    const content = (() => {
        if (!webhookResult && !webhookCreating) {
            return (
                <>
                    <h3 className="text-lg font-semibold">Set up webhook for {sourceName}</h3>
                    <p>
                        Instead of polling for changes on a schedule, we'll set up a webhook on your {sourceName}{' '}
                        account so that new data is pushed to PostHog in real-time. This means faster syncs and less
                        load on your source.
                    </p>
                    {webhookTablesList}
                    <LemonBanner type="info">
                        We'll automatically register the webhook on your {sourceName} account. No manual configuration
                        is needed.
                    </LemonBanner>
                    <LemonButton type="primary" onClick={createWebhook}>
                        Create webhook
                    </LemonButton>
                </>
            )
        }

        if (webhookCreating) {
            return (
                <>
                    <h3 className="text-lg font-semibold">Setting up webhook for {sourceName}</h3>
                    {webhookTablesList}
                    <div className="flex flex-col items-center justify-center py-8 gap-4">
                        <Spinner className="text-3xl" />
                        <p className="text-muted">Registering webhook on your {sourceName} account...</p>
                    </div>
                </>
            )
        }

        if (webhookResult?.success) {
            return (
                <>
                    <h3 className="text-lg font-semibold">Webhook created for {sourceName}</h3>
                    <LemonBanner type="success">
                        Webhook registered successfully. The tables below will now sync automatically when data changes
                        in your {sourceName} account.
                    </LemonBanner>
                    {webhookTablesList}
                </>
            )
        }

        return (
            <>
                <h3 className="text-lg font-semibold">Manual webhook setup for {sourceName}</h3>
                <LemonBanner type="warning">
                    {webhookResult?.error || 'Could not create the webhook automatically.'}
                </LemonBanner>
                <p>
                    You'll need to manually configure the webhook in your {sourceName} account. Copy the URL below and
                    add it as a webhook endpoint in your {sourceName} settings.
                </p>
                {webhookResult?.webhook_url && (
                    <div>
                        <label className="font-semibold text-sm">Webhook URL</label>
                        <div className="font-mono text-sm bg-bg-light rounded border p-2 mt-1 break-all">
                            {webhookResult.webhook_url}
                        </div>
                    </div>
                )}
                {selectedConnector?.webhookSetupCaption && (
                    <LemonMarkdown className="text-sm">{selectedConnector.webhookSetupCaption}</LemonMarkdown>
                )}
                {webhookFields.length > 0 && selectedConnector && (
                    <Form logic={sourceWizardLogic} formKey="webhookFieldInputs" enableFormOnSubmit>
                        <div className="space-y-3">
                            {webhookFields.map((field) => sourceFieldToElement(field, selectedConnector))}
                        </div>
                    </Form>
                )}
            </>
        )
    })()

    return (
        <LemonCard hoverEffect={false} className="space-y-4">
            {content}
        </LemonCard>
    )
}

function ProgressStep(): JSX.Element {
    return <SyncProgressStep />
}
