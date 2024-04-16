import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import hubspotLogo from 'public/hubspot-logo.svg'
import postgresLogo from 'public/postgres-logo.svg'
import stripeLogo from 'public/stripe-logo.svg'
import zendeskLogo from 'public/zendesk-logo.png'
import { useCallback } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SourceConfig } from '~/types'

import PostgresSchemaForm from '../external/forms/PostgresSchemaForm'
import SourceForm from '../external/forms/SourceForm'
import { SyncProgressStep } from '../external/forms/SyncProgressStep'
import { DatawarehouseTableForm } from '../new/DataWarehouseTableForm'
import { sourceWizardLogic } from './sourceWizardLogic'

export const scene: SceneExport = {
    component: NewSourceWizard,
    logic: sourceWizardLogic,
}
export function NewSourceWizard(): JSX.Element {
    const { modalTitle, modalCaption } = useValues(sourceWizardLogic)
    const { onBack, onSubmit, closeWizard, cancelWizard } = useActions(sourceWizardLogic)
    const { currentStep, isLoading, canGoBack, canGoNext, nextButtonText, showSkipButton } =
        useValues(sourceWizardLogic)

    const footer = useCallback(() => {
        if (currentStep === 1) {
            return null
        }

        return (
            <div className="mt-2 flex flex-row justify-end gap-2">
                <LemonButton
                    type="secondary"
                    center
                    data-attr="source-modal-back-button"
                    onClick={onBack}
                    disabledReason={!canGoBack && 'You cant go back from here'}
                >
                    Back
                </LemonButton>
                {showSkipButton && (
                    <LemonButton type="primary" center onClick={() => closeWizard()} data-attr="source-link">
                        Skip
                    </LemonButton>
                )}
                <LemonButton
                    loading={isLoading}
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
    }, [currentStep, isLoading, canGoNext, canGoBack, nextButtonText, showSkipButton])

    const onCancel = (): void => {
        cancelWizard()
        router.actions.push(urls.dataWarehouse())
    }

    return (
        <>
            <PageHeader
                buttons={
                    <>
                        <LemonButton type="secondary" center data-attr="source-form-cancel-button" onClick={onCancel}>
                            Cancel
                        </LemonButton>
                    </>
                }
            />
            <>
                <h3>{modalTitle}</h3>
                <p>{modalCaption}</p>
                <FirstStep />
                <SecondStep />
                <ThirdStep />
                <FourthStep />
                {footer()}
            </>
        </>
    )
}

interface ModalPageProps {
    page: number
    children?: React.ReactNode
}

function ModalPage({ children, page }: ModalPageProps): JSX.Element {
    const { currentStep } = useValues(sourceWizardLogic)

    if (currentStep !== page) {
        return <></>
    }

    return <div>{children}</div>
}

function FirstStep(): JSX.Element {
    const { connectors, addToHubspotButtonUrl } = useValues(sourceWizardLogic)
    const { selectConnector, toggleManualLinkFormVisible, onNext } = useActions(sourceWizardLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const MenuButton = (config: SourceConfig): JSX.Element => {
        const onClick = (): void => {
            selectConnector(config)
            onNext()
        }

        if (config.name === 'Stripe') {
            return (
                <LemonButton onClick={onClick} fullWidth center type="secondary">
                    <img src={stripeLogo} alt="stripe logo" height={50} />
                </LemonButton>
            )
        }
        if (config.name === 'Hubspot') {
            return (
                <LemonButton fullWidth center type="secondary" to={addToHubspotButtonUrl() || ''}>
                    <img src={hubspotLogo} alt="hubspot logo" height={45} />
                </LemonButton>
            )
        }

        if (config.name === 'Postgres' && featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_POSTGRES_IMPORT]) {
            return (
                <LemonButton onClick={onClick} fullWidth center type="secondary">
                    <div className="flex flex-row gap-2 justify-center items-center">
                        <img src={postgresLogo} alt="postgres logo" height={45} />
                        <div className="text-base">Postgres</div>
                    </div>
                </LemonButton>
            )
        }
        if (config.name === 'Zendesk') {
            return (
                <LemonButton onClick={onClick} fullWidth center type="secondary">
                    <img src={zendeskLogo} alt="Zendesk logo" height={40} />
                </LemonButton>
            )
        }

        return <></>
    }

    const onManualLinkClick = (): void => {
        toggleManualLinkFormVisible(true)
        onNext()
    }

    return (
        <ModalPage page={1}>
            <div className="flex flex-col gap-2 items-center">
                {connectors.map((config, index) => (
                    <MenuButton key={config.name + '_' + index} {...config} />
                ))}
                <LemonButton onClick={onManualLinkClick} className="w-full" center type="secondary">
                    Manual Link
                </LemonButton>
            </div>
        </ModalPage>
    )
}

function SecondStep(): JSX.Element {
    const { selectedConnector } = useValues(sourceWizardLogic)

    return (
        <ModalPage page={2}>
            {selectedConnector ? <SourceForm sourceConfig={selectedConnector} /> : <DatawarehouseTableForm />}
        </ModalPage>
    )
}

function ThirdStep(): JSX.Element {
    return (
        <ModalPage page={3}>
            <PostgresSchemaForm />
        </ModalPage>
    )
}

function FourthStep(): JSX.Element {
    return (
        <ModalPage page={4}>
            <SyncProgressStep />
        </ModalPage>
    )
}
