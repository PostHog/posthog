import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import SourceForm from 'products/data_warehouse/frontend/shared/components/forms/SourceForm'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { SessionAnalysisSetup } from '../../SessionAnalysisSetup'
import { CI_SIGNALS_REQUIRED_TABLES, signalSourcesLogic } from '../../signalSourcesLogic'
import { AgentsRoster } from './AgentsRoster'

// Each signal source reads from specific tables – pre-select them and make them required
const SIGNAL_SOURCE_REQUIRED_TABLES: Partial<Record<ExternalDataSourceType, string[]>> = {
    Github: ['issues'],
    Linear: ['issues'],
    Zendesk: ['tickets'],
    PgAnalyze: ['issues', 'servers'],
}

function BackLink({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={onClick} className="-ml-2 w-fit">
            Back
        </LemonButton>
    )
}

/**
 * Signal sources management: the per-source roster (each source watches for signals and
 * spins up work when something matters), plus the session-analysis and data-source setup
 * sub-flows that render inline (replacing the roster) when their flow is open. Hosted in
 * the Signal sources setup modal.
 */
export function SignalSourcesPanel(): JSX.Element {
    const { sessionAnalysisSetupOpen, dataSourceSetupProduct } = useValues(signalSourcesLogic)
    const {
        loadSources,
        loadSourceConfigs,
        closeSessionAnalysisSetup,
        closeDataSourceSetup,
        onDataSourceSetupComplete,
    } = useActions(signalSourcesLogic)

    useEffect(() => {
        loadSources()
        loadSourceConfigs()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    if (dataSourceSetupProduct !== null) {
        return (
            <div className="flex flex-col gap-3">
                <BackLink onClick={closeDataSourceSetup} />
                <DataSourceSetup
                    product={dataSourceSetupProduct}
                    onComplete={() => onDataSourceSetupComplete(dataSourceSetupProduct)}
                />
            </div>
        )
    }

    if (sessionAnalysisSetupOpen) {
        return (
            <div className="flex flex-col gap-3">
                <BackLink onClick={closeSessionAnalysisSetup} />
                <SessionAnalysisSetup />
            </div>
        )
    }

    return <AgentsRoster />
}

function DataSourceSetup({
    product,
    onComplete,
}: {
    product: ExternalDataSourceType
    onComplete: () => void
}): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)
    const { dataSourceSetupIntent } = useValues(signalSourcesLogic)

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
                requiredTables:
                    dataSourceSetupIntent === 'ci_signals'
                        ? CI_SIGNALS_REQUIRED_TABLES
                        : SIGNAL_SOURCE_REQUIRED_TABLES[product],
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
