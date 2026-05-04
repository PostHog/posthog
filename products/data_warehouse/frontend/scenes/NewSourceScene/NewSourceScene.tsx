import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { IconCopy, IconQuestion } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonModal,
    LemonSkeleton,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { nonHogFunctionTemplatesLogic } from 'scenes/data-pipelines/utils/nonHogFunctionTemplatesLogic'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import SchemaForm from '../../shared/components/forms/SchemaForm'
import SourceForm, { SourceAccessMethodSelector } from '../../shared/components/forms/SourceForm'
import { SyncProgressStep } from '../../shared/components/forms/SyncProgressStep'
import { WebhookSetupForm } from '../../shared/components/forms/WebhookSetupForm'
import { FreeHistoricalSyncsBanner } from '../../shared/components/FreeHistoricalSyncsBanner'
import { SourceIcon } from '../../shared/components/SourceIcon'
import { availableSourcesLogic } from './availableSourcesLogic'
import { BillingLimitNotice } from './components/BillingLimitNotice'
import { SelfManagedSourceForm } from './components/SelfManagedSourceForm'
import { selfManagedSourceLogic } from './selfManagedSourceLogic'
import { sourceWizardLogic } from './sourceWizardLogic'

export const getEffectiveAccessMethod = (
    currentStep: number,
    draftAccessMethod: 'warehouse' | 'direct' | undefined,
    persistedAccessMethod: 'warehouse' | 'direct'
): 'warehouse' | 'direct' => {
    if (currentStep === 2 && draftAccessMethod) {
        return draftAccessMethod
    }
    return persistedAccessMethod
}

export const scene: SceneExport = {
    component: NewSourceScene,
    // logic: sourceWizardLogic, // NOTE: We can't mount it here as it needs the availableSourcesLogic to be mounted first
}

export function NewSourceScene(): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    return (
        <BindLogic logic={sourceWizardLogic} props={{ availableSources }}>
            <InternalNewSourceScene />
        </BindLogic>
    )
}

function InternalNewSourceScene(): JSX.Element {
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
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

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
        sourceConnectionDetails,
    } = useValues(sourceWizardLogic)
    const { onBack, onSubmit, setInitialConnector, setSourceConnectionDetailsValue, updateSource } =
        useActions(sourceWizardLogic)
    const selectedAccessMethod = getEffectiveAccessMethod(
        currentStep,
        sourceConnectionDetails?.access_method,
        source.access_method
    )
    const showAccessMethodSelector = currentStep === 2 && selectedConnector?.name === 'Postgres'
    const { tableLoading: manualLinkIsLoading } = useValues(selfManagedSourceLogic)

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
            <div className="flex flex-row gap-2 justify-end my-4">
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
            {!isWrapped && <BillingLimitNotice />}
            <>
                {showAccessMethodSelector && (
                    <>
                        <SourceAccessMethodSelector
                            value={selectedAccessMethod}
                            onChange={(accessMethod) => {
                                updateSource({ access_method: accessMethod })
                                setSourceConnectionDetailsValue('access_method', accessMethod)
                            }}
                        />
                        <LemonDivider className="my-4" />
                    </>
                )}

                {selectedConnector && (
                    <div className="flex items-center gap-3 mb-4">
                        <SourceIcon type={selectedConnector.name} size="small" disableTooltip />
                        <div>
                            <h4 className="text-lg font-semibold mb-0">{modalTitle}</h4>
                            <p className="text-sm text-muted-alt mb-0">
                                {selectedAccessMethod === 'direct'
                                    ? `Query selected ${selectedConnector.label ?? selectedConnector.name} tables live from PostHog. Tables stay in the source database and are not synced into the data warehouse.`
                                    : `Sync data from ${selectedConnector.label ?? selectedConnector.name} into the PostHog data warehouse.`}
                            </p>
                        </div>
                    </div>
                )}

                {selectedConnector && selectedAccessMethod !== 'direct' && (
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
            <CDCSelfManagedSetupDialog />
        </div>
    )
}

function CDCSelfManagedSetupDialog(): JSX.Element | null {
    const {
        cdcSelfManagedSetupDialogOpen,
        source,
        databaseSchema,
        sourceConnectionDetails,
        cdcSelfManagedVerifyResult,
        cdcSelfManagedVerifyResultLoading,
    } = useValues(sourceWizardLogic)
    const { closeCdcSelfManagedSetupDialog, verifyCdcSelfManagedSetup } = useActions(sourceWizardLogic)

    // Checkbox state is pure UI toggle — no business logic, stays local.
    const [confirmed, setConfirmed] = useState(false)

    const payload = (source?.payload || {}) as Record<string, any>
    const cdcTableNames = useMemo(
        () =>
            (databaseSchema || [])
                .filter((s: any) => s.should_sync && s.sync_type === 'cdc')
                .map((s: any) => s.table as string),
        [databaseSchema]
    )
    const schema = (sourceConnectionDetails?.payload?.schema as string) || 'public'
    const pubName = (payload.cdc_publication_name as string) || 'posthog_pub'
    const dbUser = (sourceConnectionDetails?.payload?.user as string) || '<your_user>'

    const tableList =
        cdcTableNames.length > 0
            ? cdcTableNames.map((t) => `"${schema}"."${t}"`).join(', ')
            : `"${schema}"."your_table"`

    const sql = `-- 1. Grants for the PostHog user
--    Reading a replication slot requires REPLICATION (or rds_replication on RDS).
--    Run ONE of the lines below, depending on your environment:
ALTER USER "${dbUser}" WITH REPLICATION;             -- self-hosted / most clouds
-- GRANT rds_replication TO "${dbUser}";             -- AWS RDS
GRANT USAGE ON SCHEMA "${schema}" TO "${dbUser}";
GRANT SELECT ON ${tableList} TO "${dbUser}";

-- 2. Publication covering the ${cdcTableNames.length} selected table${cdcTableNames.length === 1 ? '' : 's'}
--    Run this as the table owner (or a superuser). PostHog will create and manage
--    the replication slot itself once the source is created.
CREATE PUBLICATION "${pubName}" FOR TABLE ${tableList}
  WITH (publish_via_partition_root = true);

-- Later, to add a new table to the publication:
-- ALTER PUBLICATION "${pubName}" ADD TABLE "${schema}"."new_table";`

    const handleCopy = async (): Promise<void> => {
        await copyToClipboard(sql, 'Setup SQL')
    }

    if (!cdcSelfManagedSetupDialogOpen) {
        return null
    }

    const errors =
        cdcSelfManagedVerifyResult && !cdcSelfManagedVerifyResult.valid ? cdcSelfManagedVerifyResult.errors : null

    return (
        <LemonModal
            isOpen
            onClose={closeCdcSelfManagedSetupDialog}
            title="Create your publication"
            description={`Self-managed CDC needs the publication to exist before PostHog connects — PostHog will create and manage the replication slot itself. Run the SQL below (covering the ${cdcTableNames.length} table${cdcTableNames.length === 1 ? '' : 's'} you selected for CDC) as the table owner, then click Verify & create.`}
            width={720}
            footer={
                <>
                    <LemonButton
                        type="tertiary"
                        onClick={closeCdcSelfManagedSetupDialog}
                        disabledReason={cdcSelfManagedVerifyResultLoading ? 'Verifying...' : undefined}
                    >
                        Back
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={cdcSelfManagedVerifyResultLoading}
                        disabledReason={!confirmed ? 'Confirm you have executed the SQL' : undefined}
                        onClick={verifyCdcSelfManagedSetup}
                    >
                        Verify & create source
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3">
                <div className="flex justify-end">
                    <LemonButton size="small" type="secondary" icon={<IconCopy />} onClick={() => void handleCopy()}>
                        Copy SQL
                    </LemonButton>
                </div>
                <pre className="text-xs bg-surface-primary p-3 rounded overflow-x-auto whitespace-pre-wrap border border-border">
                    {sql}
                </pre>

                <LemonCheckbox
                    checked={confirmed}
                    onChange={setConfirmed}
                    label="I have executed the SQL above on my PostgreSQL database"
                />

                {errors && errors.length > 0 && (
                    <LemonBanner type="error">
                        <p className="font-semibold mb-1">Verification failed — please fix the following and retry:</p>
                        <ul className="list-disc ml-5 mb-0 text-sm">
                            {errors.map((err, i) => (
                                <li key={i}>{err}</li>
                            ))}
                        </ul>
                    </LemonBanner>
                )}
            </div>
        </LemonModal>
    )
}

function FirstStep({ allowedSources }: NewSourcesWizardProps): JSX.Element {
    const { availableSourcesLoading } = useValues(availableSourcesLogic)
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
    const { selectedConnector, source, sourceConnectionDetails } = useValues(sourceWizardLogic)
    const selectedAccessMethod = getEffectiveAccessMethod(
        2,
        sourceConnectionDetails?.access_method,
        source.access_method
    )

    return selectedConnector ? (
        <div className="space-y-4">
            {selectedConnector.caption && selectedAccessMethod !== 'direct' && (
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

            <SourceForm
                sourceConfig={selectedConnector}
                initialAccessMethod={sourceConnectionDetails?.access_method ?? source.access_method}
                showAccessMethodSelector={false}
            />
        </div>
    ) : (
        <BindLogic logic={selfManagedSourceLogic} props={{ id: 'new' }}>
            <SelfManagedSourceForm />
        </BindLogic>
    )
}

function ThirdStep(): JSX.Element {
    return <SchemaForm />
}

function WebhookSetupStep(): JSX.Element {
    const { webhookResult, webhookCreating, selectedConnector, databaseSchema } = useValues(sourceWizardLogic)
    const { createWebhook } = useActions(sourceWizardLogic)

    const webhookTables = databaseSchema
        .filter((s) => s.supports_webhooks && s.sync_type === 'webhook' && s.should_sync)
        .map((s) => ({ name: s.table, label: s.label }))

    return (
        <WebhookSetupForm
            sourceName={selectedConnector?.label ?? selectedConnector?.name ?? 'source'}
            sourceConfig={selectedConnector}
            webhookTables={webhookTables}
            webhookResult={webhookResult}
            webhookCreating={webhookCreating}
            onCreateWebhook={createWebhook}
            formLogic={sourceWizardLogic}
            formKey="webhookFieldInputs"
        />
    )
}

function ProgressStep(): JSX.Element {
    return <SyncProgressStep />
}
