import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect } from 'react'

import { LemonButton, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { nonHogFunctionTemplatesLogic } from 'scenes/data-pipelines/utils/nonHogFunctionTemplatesLogic'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

import { DataWarehouseInitialBillingLimitNotice } from '../DataWarehouseInitialBillingLimitNotice'
import SchemaForm from '../external/forms/SchemaForm'
import SourceForm from '../external/forms/SourceForm'
import { SyncProgressStep } from '../external/forms/SyncProgressStep'
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
            <SceneDivider />
            <InternalSourcesWizard />
        </SceneContent>
    )
}

interface NewSourcesWizardProps {
    onComplete?: () => void
    allowedSources?: ExternalDataSourceType[] // Filter to only show these source types
    initialSource?: ExternalDataSourceType // Pre-select this source and start on step 2
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
    } = useValues(sourceWizardLogic)
    const { onBack, onSubmit, setInitialConnector } = useActions(sourceWizardLogic)
    const { tableLoading: manualLinkIsLoading } = useValues(dataWarehouseTableLogic)

    // Initialize wizard with initial source if provided
    useEffect(() => {
        if (props.initialSource && connectors.length > 0) {
            const initialConnector = connectors.find((c) => c.name === props.initialSource)
            if (initialConnector) {
                setInitialConnector(initialConnector)
            }
        }
    }, [props.initialSource, connectors, setInitialConnector])

    const footer = useCallback(() => {
        if (currentStep === 1) {
            return null
        }

        return (
            <div className="flex flex-row gap-2 justify-end mt-4">
                <LemonButton
                    type="secondary"
                    center
                    data-attr="source-modal-back-button"
                    onClick={onBack}
                    disabledReason={!canGoBack && 'You cant go back from here'}
                >
                    Back
                </LemonButton>
                <LemonButton
                    loading={isLoading || manualLinkIsLoading}
                    disabledReason={!canGoNext && 'You cant click next yet'}
                    type="primary"
                    center
                    onClick={() => onSubmit()}
                    data-attr="source-link"
                >
                    {nextButtonText}
                </LemonButton>
            </div>
        )
    }, [currentStep, canGoBack, onBack, isLoading, manualLinkIsLoading, canGoNext, nextButtonText, onSubmit])

    return (
        <>
            {!isWrapped && <DataWarehouseInitialBillingLimitNotice />}
            <>
                {selectedConnector && (
                    <div className="flex items-center gap-3 mb-4">
                        <DataWarehouseSourceIcon type={selectedConnector.name} size="small" disableTooltip />
                        <div>
                            <h4 className="text-lg font-semibold mb-0">{modalTitle}</h4>
                            <p className="text-sm text-muted-alt mb-0">
                                Import data directly from {selectedConnector.label ?? selectedConnector.name}
                            </p>
                        </div>
                    </div>
                )}

                {currentStep === 1 ? (
                    <FirstStep allowedSources={props.allowedSources} />
                ) : currentStep === 2 ? (
                    <SecondStep />
                ) : currentStep === 3 ? (
                    <ThirdStep />
                ) : currentStep === 4 ? (
                    <FourthStep />
                ) : (
                    <div>Something went wrong...</div>
                )}

                {footer()}
            </>
        </>
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

            {selectedConnector.docsUrl && (
                <div className="inline-block">
                    <LemonButton to={selectedConnector.docsUrl} type="primary" size="small">
                        View docs
                    </LemonButton>
                </div>
            )}

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

function FourthStep(): JSX.Element {
    return <SyncProgressStep />
}
