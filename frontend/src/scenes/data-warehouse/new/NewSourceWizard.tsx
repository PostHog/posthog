import { LemonButton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { useCallback, useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { DataWarehouseInitialBillingLimitNotice } from '../DataWarehouseInitialBillingLimitNotice'
import SchemaForm from '../external/forms/SchemaForm'
import SourceForm from '../external/forms/SourceForm'
import { SyncProgressStep } from '../external/forms/SyncProgressStep'
import { DatawarehouseTableForm } from '../new/DataWarehouseTableForm'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'
import { NewSourcesList, NewSourcesListProps } from './NewSourcesList'
import { sourceWizardLogic } from './sourceWizardLogic'

export const scene: SceneExport = {
    component: NewSourceWizardScene,
    logic: sourceWizardLogic,
}

export function NewSourceWizardScene(): JSX.Element {
    const { closeWizard } = useActions(sourceWizardLogic)

    return (
        <>
            <PageHeader
                buttons={
                    <>
                        <LemonButton
                            type="secondary"
                            center
                            data-attr="source-form-cancel-button"
                            onClick={closeWizard}
                        >
                            Cancel
                        </LemonButton>
                    </>
                }
            />
            <NewSourcesWizard />
        </>
    )
}

interface NewSourcesWizardProps {
    disableConnectedSources?: boolean
    onComplete?: () => void
}

export function NewSourcesWizard(props: NewSourcesWizardProps): JSX.Element {
    const { onComplete } = props
    const wizardLogic = sourceWizardLogic({ onComplete })

    const { modalTitle, modalCaption, isWrapped, currentStep, isLoading, canGoBack, canGoNext, nextButtonText } =
        useValues(wizardLogic)
    const { onBack, onSubmit, onClear } = useActions(wizardLogic)
    const { tableLoading: manualLinkIsLoading } = useValues(dataWarehouseTableLogic)

    useEffect(() => {
        return () => {
            onClear()
        }
    }, [onClear])

    const footer = useCallback(() => {
        if (currentStep === 1) {
            return null
        }

        return (
            <div className="flex flex-row gap-2 justify-end mt-4">
                {canGoBack && (
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
                <h3>{modalTitle}</h3>
                <p>{modalCaption}</p>

                {currentStep === 1 ? (
                    <FirstStep {...props} />
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

function FirstStep({ disableConnectedSources }: NewSourcesListProps): JSX.Element {
    return <NewSourcesList disableConnectedSources={disableConnectedSources} />
}

function SecondStep(): JSX.Element {
    const { selectedConnector } = useValues(sourceWizardLogic)

    return selectedConnector ? (
        <SourceForm sourceConfig={selectedConnector} />
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
