import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { AllowTrainingCallout } from 'lib/components/AllowTrainingCallout/AllowTrainingCallout'
import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import SourceForm from 'products/data_warehouse/frontend/shared/components/forms/SourceForm'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'
import { CodingAgentEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxSceneLogic } from './inboxSceneLogic'
import { SessionAnalysisSetup } from './SessionAnalysisSetup'
import { signalSourcesLogic } from './signalSourcesLogic'
import { SourcesList } from './SourcesList'

// Each signal source reads from specific tables — pre-select them and make them required
const SIGNAL_SOURCE_REQUIRED_TABLES: Partial<Record<ExternalDataSourceType, string[]>> = {
    Github: ['issues'],
    Linear: ['issues'],
    Zendesk: ['tickets'],
    PgAnalyze: ['issues', 'servers'],
}

export function SourcesModal(): JSX.Element {
    const { sourcesModalOpen, sessionAnalysisSetupOpen, dataSourceSetupProduct } = useValues(signalSourcesLogic)
    const { closeSourcesModal, closeSessionAnalysisSetup, closeDataSourceSetup, onDataSourceSetupComplete } =
        useActions(signalSourcesLogic)
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti({ count: 30, duration: 3000 })

    const isDataSourceSetupOpen = dataSourceSetupProduct !== null

    const handleDataSourceComplete = (): void => {
        triggerHogfetti()
        setTimeout(() => {
            triggerHogfetti()
        }, 200)
        setTimeout(() => {
            triggerHogfetti()
        }, 400)
        onDataSourceSetupComplete(dataSourceSetupProduct!)
    }

    return (
        <>
            <LemonModal
                isOpen={sourcesModalOpen}
                onClose={closeSourcesModal}
                simple
                width={sessionAnalysisSetupOpen || isDataSourceSetupOpen ? '48rem' : '32rem'}
            >
                <LemonModal.Header>
                    <div className="flex items-center gap-2">
                        {(sessionAnalysisSetupOpen || isDataSourceSetupOpen) && (
                            <LemonButton
                                type="tertiary"
                                size="small"
                                icon={<IconArrowLeft />}
                                onClick={isDataSourceSetupOpen ? closeDataSourceSetup : closeSessionAnalysisSetup}
                            />
                        )}
                        <h3 className="font-semibold mb-0">
                            {isDataSourceSetupOpen
                                ? `Connect ${dataSourceSetupProduct}`
                                : sessionAnalysisSetupOpen
                                  ? 'Session analysis filters'
                                  : 'Signal sources'}
                        </h3>
                    </div>
                    {!sessionAnalysisSetupOpen && !isDataSourceSetupOpen && (
                        <p className="text-xs text-secondary mt-1 mb-0">Set up sources feeding the Inbox.</p>
                    )}
                </LemonModal.Header>
                <LemonModal.Content className={sessionAnalysisSetupOpen ? 'p-0 rounded-b' : ''}>
                    <AllowTrainingCallout featureName="Inbox" className="mb-5" />
                    {isDataSourceSetupOpen ? (
                        <DataSourceSetup product={dataSourceSetupProduct} onComplete={handleDataSourceComplete} />
                    ) : sessionAnalysisSetupOpen ? (
                        <SessionAnalysisSetup />
                    ) : (
                        <>
                            <CodingAgentSettings />
                            <SourcesList />
                        </>
                    )}
                </LemonModal.Content>
            </LemonModal>
            {createPortal(
                <HogfettiComponent />,
                document.body /* Needs to be in portal to be above ReactModalPortal */
            )}
        </>
    )
}

function CodingAgentSettings(): JSX.Element | null {
    const {
        canDispatch,
        defaultCodingAgent,
        cursorConnected,
        cursorConnectionWarning,
        cursorConnectionLoading,
        cursorApiKeyDraft,
    } = useValues(inboxSceneLogic)
    const { saveTeamDefaultAgent, connectCursor, disconnectCursor, setCursorApiKeyDraft } = useActions(inboxSceneLogic)

    if (!canDispatch) {
        return null
    }

    return (
        <div className="mb-5 pb-5 border-b border-border">
            <h4 className="font-semibold mb-1">Coding agent</h4>
            <p className="text-xs text-secondary mb-2">
                Which agent acts on reports — the default for each report's button and for the automatic autonomy path.
                Connecting Cursor doesn't change this; you choose the default here.
            </p>
            <LemonSelect
                value={defaultCodingAgent}
                onChange={(agent) => saveTeamDefaultAgent({ agent })}
                options={[
                    { value: CodingAgentEnumApi.PosthogCode, label: 'PostHog Code' },
                    { value: CodingAgentEnumApi.Cursor, label: 'Cursor' },
                ]}
                data-attr="default-coding-agent-select"
            />
            <div className="mt-3">
                {cursorConnected ? (
                    <div className="flex items-center gap-2">
                        <span className="text-sm">Cursor connected</span>
                        <LemonButton
                            size="small"
                            status="danger"
                            onClick={() => disconnectCursor()}
                            data-attr="disconnect-cursor-button"
                        >
                            Disconnect
                        </LemonButton>
                    </div>
                ) : (
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="password"
                            value={cursorApiKeyDraft}
                            onChange={setCursorApiKeyDraft}
                            placeholder="crsr_..."
                            data-attr="settings-cursor-key-input"
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={cursorConnectionLoading}
                            disabledReason={!cursorApiKeyDraft ? 'Enter your Cursor API key' : undefined}
                            onClick={() => connectCursor({ apiKey: cursorApiKeyDraft })}
                            data-attr="settings-connect-cursor-button"
                        >
                            Connect Cursor
                        </LemonButton>
                    </div>
                )}
                {cursorConnectionWarning && (
                    <LemonBanner type="warning" className="mt-2">
                        {cursorConnectionWarning}
                    </LemonBanner>
                )}
            </div>
        </div>
    )
}

function DataSourceSetup({
    product,
    onComplete,
}: {
    product: ExternalDataSourceType
    onComplete: () => void
}): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    const sourceConfig = Object.values(availableSources).find((s: SourceConfig) => s.name === product)
    if (!sourceConfig) {
        return <div>Source not found</div>
    }

    return (
        <BindLogic
            logic={sourceWizardLogic}
            props={{
                availableSources,
                requiredTables: SIGNAL_SOURCE_REQUIRED_TABLES[product],
                onComplete,
            }}
        >
            <DataSourceSetupForm sourceConfig={sourceConfig} />
        </BindLogic>
    )
}

function DataSourceSetupForm({ sourceConfig }: { sourceConfig: SourceConfig }): JSX.Element {
    const { isLoading, canGoNext } = useValues(sourceWizardLogic)
    const { setInitialConnector, onSubmit } = useActions(sourceWizardLogic)

    // Set up the connector so sourceWizardLogic knows what source type we're connecting
    useEffect(() => {
        setInitialConnector(sourceConfig)
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-3">
                <SourceIcon type={sourceConfig.name} size="small" disableTooltip />
                <p className="text-sm text-muted-alt mb-0">
                    Connect {sourceConfig.label ?? sourceConfig.name} as a data source to enable this signal.
                </p>
            </div>

            <SourceForm sourceConfig={sourceConfig} showPrefix={false} />

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    loading={isLoading}
                    disabledReason={!canGoNext ? 'Fill in the required fields' : undefined}
                    onClick={() => onSubmit()}
                >
                    Connect
                </LemonButton>
            </div>
        </div>
    )
}
