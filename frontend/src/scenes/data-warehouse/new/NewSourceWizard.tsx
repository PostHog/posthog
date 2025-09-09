import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useEffect } from 'react'

import { IconBell, IconCheck } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTable, LemonTag, Link, lemonToast } from '@posthog/lemon-ui'

import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { IconBlank } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { SceneExport } from 'scenes/sceneTypes'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'
import { ManualLinkSourceType, SurveyEventName, SurveyEventProperties } from '~/types'

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
            <InternalSourcesWizard />
        </>
    )
}

interface NewSourcesWizardProps {
    onComplete?: () => void
    disableConnectedSources?: boolean
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
    const { onBack, onSubmit, onClear, setInitialConnector } = useActions(sourceWizardLogic)
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

    useEffect(() => onClear, [onClear])

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
                    <FirstStep
                        disableConnectedSources={props.disableConnectedSources}
                        allowedSources={props.allowedSources}
                    />
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

function FirstStep({ disableConnectedSources, allowedSources }: NewSourcesWizardProps): JSX.Element {
    const { connectors, manualConnectors } = useValues(sourceWizardLogic)
    const { selectConnector, toggleManualLinkFormVisible, onNext, setManualLinkingProvider } =
        useActions(sourceWizardLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const onClick = (sourceConfig: SourceConfig): void => {
        selectConnector(sourceConfig)
        onNext()
    }

    const onManualLinkClick = (manualLinkSource: ManualLinkSourceType): void => {
        toggleManualLinkFormVisible(true)
        setManualLinkingProvider(manualLinkSource)
    }

    const filteredConnectors = connectors
        .filter((n) => {
            if (n.name === 'MetaAds') {
                return featureFlags[FEATURE_FLAGS.META_ADS_DWH]
            }

            // Filter by allowed sources if specified
            if (allowedSources && allowedSources.length > 0) {
                return allowedSources.includes(n.name)
            }

            return true
        })
        .sort((a, b) => Number(a.unreleasedSource) - Number(b.unreleasedSource))

    return (
        <>
            <h2 className="mt-4">Managed data warehouse sources</h2>

            <p>
                Data will be synced to PostHog and regularly refreshed.{' '}
                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
            </p>
            <LemonTable
                dataSource={filteredConnectors}
                loading={false}
                disableTableWhileLoading={false}
                columns={[
                    {
                        title: 'Source',
                        width: 0,
                        render: function (_, sourceConfig) {
                            return sourceConfig.name ? (
                                <DataWarehouseSourceIcon type={sourceConfig.name} />
                            ) : (
                                <IconBlank />
                            )
                        },
                    },
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, sourceConfig) => (
                            <div className="flex flex-col">
                                <span className="gap-1 text-sm font-semibold">
                                    {sourceConfig.label ?? sourceConfig.name}
                                    {sourceConfig.betaSource && (
                                        <span>
                                            {' '}
                                            <LemonTag type="warning">BETA</LemonTag>
                                        </span>
                                    )}
                                </span>
                                {sourceConfig.unreleasedSource && (
                                    <span>Get notified when {sourceConfig.label} is available to connect</span>
                                )}
                            </div>
                        ),
                    },
                    {
                        key: 'actions',
                        render: (_, sourceConfig) => {
                            const isConnected = disableConnectedSources && sourceConfig.existingSource

                            return (
                                <div className="flex flex-row justify-end p-1">
                                    {isConnected && (
                                        <LemonTag type="success" className="my-4" size="medium">
                                            <IconCheck />
                                            Connected
                                        </LemonTag>
                                    )}
                                    {!isConnected && sourceConfig.unreleasedSource === true && (
                                        <LemonButton
                                            className="my-2"
                                            type="primary"
                                            icon={<IconBell />}
                                            onClick={() => {
                                                // https://us.posthog.com/project/2/surveys/0190ff15-5032-0000-722a-e13933c140ac
                                                posthog.capture(SurveyEventName.SENT, {
                                                    [SurveyEventProperties.SURVEY_ID]:
                                                        '0190ff15-5032-0000-722a-e13933c140ac',
                                                    [`${SurveyEventProperties.SURVEY_RESPONSE}_ad030277-3642-4abf-b6b0-7ecb449f07e8`]:
                                                        sourceConfig.label ?? sourceConfig.name,
                                                })
                                                posthog.capture('source_notify_me', {
                                                    source: sourceConfig.label ?? sourceConfig.name,
                                                })
                                                lemonToast.success('Notification registered successfully')
                                            }}
                                        >
                                            Notify me
                                        </LemonButton>
                                    )}
                                    {!isConnected && !sourceConfig.unreleasedSource && (
                                        <LemonButton
                                            onClick={() => onClick(sourceConfig)}
                                            className="my-2"
                                            type="primary"
                                            disabledReason={
                                                disableConnectedSources && sourceConfig.existingSource
                                                    ? 'You have already connected this source'
                                                    : undefined
                                            }
                                        >
                                            Link
                                        </LemonButton>
                                    )}
                                </div>
                            )
                        },
                    },
                ]}
            />

            <h2 className="mt-4">Self-managed data warehouse sources</h2>

            <p>
                Data will be queried directly from your data source that you manage.{' '}
                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
            </p>
            <LemonTable
                dataSource={manualConnectors}
                loading={false}
                disableTableWhileLoading={false}
                columns={[
                    {
                        title: 'Source',
                        width: 0,
                        render: (_, sourceConfig) => <DataWarehouseSourceIcon type={sourceConfig.type} />,
                    },
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, sourceConfig) => (
                            <span className="gap-1 text-sm font-semibold">{sourceConfig.name}</span>
                        ),
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, sourceConfig) => (
                            <div className="flex flex-row justify-end p-1">
                                <LemonButton
                                    onClick={() => onManualLinkClick(sourceConfig.type)}
                                    className="my-2"
                                    type="primary"
                                >
                                    Link
                                </LemonButton>
                            </div>
                        ),
                    },
                ]}
            />
        </>
    )
}

function SecondStep(): JSX.Element {
    const { selectedConnector } = useValues(sourceWizardLogic)

    return selectedConnector ? (
        <div className="space-y-4">
            {selectedConnector.caption && (
                <LemonMarkdown className="text-sm">{selectedConnector.caption}</LemonMarkdown>
            )}

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
