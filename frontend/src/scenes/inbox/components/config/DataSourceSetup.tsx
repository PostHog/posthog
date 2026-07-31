import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SourceConfig } from '~/queries/schema/schema-general'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import SourceForm from 'products/data_warehouse/frontend/shared/components/forms/SourceForm'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { WAREHOUSE_SOURCE_SETUP, WarehouseBackedSource } from '../../signalSourcesLogic'

/** Connect-a-warehouse-source flow for a signal source; tables and wizard product come from its registration. */
export function DataSourceSetup({
    source,
    onComplete,
}: {
    source: WarehouseBackedSource
    onComplete: () => void
}): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)
    const { dwSourceType, requiredTables } = WAREHOUSE_SOURCE_SETUP[source]

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    const sourceConfig = Object.values(availableSources).find((s: SourceConfig) => s.name === dwSourceType)
    if (!sourceConfig) {
        return <div>Source not found</div>
    }

    return (
        <BindLogic
            logic={sourceWizardLogic}
            props={{
                availableSources,
                requiredTables,
                onComplete,
            }}
        >
            <DataSourceSetupForm sourceConfig={sourceConfig} source={source} />
        </BindLogic>
    )
}

function DataSourceSetupForm({
    sourceConfig,
    source,
}: {
    sourceConfig: SourceConfig
    source: WarehouseBackedSource
}): JSX.Element {
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

            <SourceForm
                sourceConfig={sourceConfig}
                showPrefix={false}
                // Keeps an OAuth round-trip (e.g. GitHub) on this inbox panel instead of the standalone
                // new-source scene — AgentSetupColumn resumes the flow from the `dataSource` param.
                oauthRedirectUrl={`${urls.inbox('config')}?dataSource=${source}`}
            />

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
