import { LemonButton, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { useCallback } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ManualLinkSourceType, SourceConfig } from '~/types'

import { DataWarehouseBetaNotice } from '../DataWarehouseBetaNotice'
import PostgresSchemaForm from '../external/forms/PostgresSchemaForm'
import SourceForm from '../external/forms/SourceForm'
import { SyncProgressStep } from '../external/forms/SyncProgressStep'
import { DatawarehouseTableForm } from '../new/DataWarehouseTableForm'
import { RenderDataWarehouseSourceIcon } from '../settings/DataWarehouseSourcesTable'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'
import { sourceWizardLogic } from './sourceWizardLogic'

export const scene: SceneExport = {
    component: NewSourceWizard,
    logic: sourceWizardLogic,
}
export function NewSourceWizard(): JSX.Element {
    const { modalTitle, modalCaption } = useValues(sourceWizardLogic)
    const { onBack, onSubmit, closeWizard } = useActions(sourceWizardLogic)
    const { currentStep, isLoading, canGoBack, canGoNext, nextButtonText, showSkipButton } =
        useValues(sourceWizardLogic)
    const { tableLoading: manualLinkIsLoading } = useValues(dataWarehouseTableLogic)

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
    }, [currentStep, isLoading, manualLinkIsLoading, canGoNext, canGoBack, nextButtonText, showSkipButton])

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
            <DataWarehouseBetaNotice />
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
    const { connectors, manualConnectors, addToHubspotButtonUrl } = useValues(sourceWizardLogic)
    const { selectConnector, toggleManualLinkFormVisible, onNext, setManualLinkingProvider } =
        useActions(sourceWizardLogic)

    const onClick = (sourceConfig: SourceConfig): void => {
        if (sourceConfig.name == 'Hubspot') {
            window.open(addToHubspotButtonUrl() as string)
        } else {
            selectConnector(sourceConfig)
        }
        onNext()
    }

    const onManualLinkClick = (manulLinkSource: ManualLinkSourceType): void => {
        toggleManualLinkFormVisible(true)
        setManualLinkingProvider(manulLinkSource)
    }

    return (
        <ModalPage page={1}>
            <h2 className="mt-4">Managed by PostHog</h2>

            <span>
                Data will be synced to PostHog and regularly refreshed.{' '}
                <Link to="https://posthog.com/docs/data-warehouse/setup#stripe">Learn more</Link>
            </span>
            <LemonTable
                dataSource={connectors}
                loading={false}
                disableTableWhileLoading={false}
                columns={[
                    {
                        title: 'Source',
                        width: 0,
                        render: function RenderAppInfo(_, sourceConfig) {
                            return <RenderDataWarehouseSourceIcon type={sourceConfig.name} />
                        },
                    },
                    {
                        title: 'Name',
                        key: 'name',
                        render: function RenderName(_, sourceConfig) {
                            return <span className="font-semibold text-sm gap-1">{sourceConfig.name}</span>
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: function RenderActions(_, sourceConfig) {
                            return (
                                <div className="flex flex-row justify-end">
                                    <LemonButton onClick={() => onClick(sourceConfig)} className="my-2" type="primary">
                                        Link
                                    </LemonButton>
                                </div>
                            )
                        },
                    },
                ]}
            />

            <h2 className="mt-4">Self Managed</h2>

            <span>
                Data will be queried directly from your data source that you manage.{' '}
                <Link to="https://posthog.com/docs/data-warehouse/setup#linking-a-custom-source">Learn more</Link>
            </span>
            <LemonTable
                dataSource={manualConnectors}
                loading={false}
                disableTableWhileLoading={false}
                columns={[
                    {
                        title: 'Source',
                        width: 0,
                        render: function RenderAppInfo(_, sourceConfig) {
                            return <RenderDataWarehouseSourceIcon type={sourceConfig.type} />
                        },
                    },
                    {
                        title: 'Name',
                        key: 'name',
                        render: function RenderName(_, sourceConfig) {
                            return <span className="font-semibold text-sm gap-1">{sourceConfig.name}</span>
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: function RenderActions(_, sourceConfig) {
                            return (
                                <div className="flex flex-row justify-end">
                                    <LemonButton
                                        onClick={() => onManualLinkClick(sourceConfig.type)}
                                        className="my-2"
                                        type="primary"
                                    >
                                        Link
                                    </LemonButton>
                                </div>
                            )
                        },
                    },
                ]}
            />
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
