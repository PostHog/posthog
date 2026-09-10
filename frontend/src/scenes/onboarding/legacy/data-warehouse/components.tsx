import { useValues } from 'kea'

import { SourceConfig } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'

import { OnboardingStep } from '../OnboardingStep'

export function DataWarehouseOnboardingLoadingPlaceholder(): JSX.Element {
    return (
        <OnboardingStep title="Import data" stepKey={OnboardingStepKey.LINK_DATA} showContinue={false} showSkip={false}>
            <div className="h-64" />
        </OnboardingStep>
    )
}

// An OAuth round-trip returns to this step with ?kind=<source>; start on the setup phase so
// InlineSourceSetup is mounted to resume the wizard rather than showing the value-prop screen.
export function initialOnboardingPhase(): 'value-prop' | 'setup' {
    return new URLSearchParams(window.location.search).get('kind') ? 'setup' : 'value-prop'
}

export function useDataWarehouseLoadingState(): { isLoading: boolean } {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)
    return { isLoading: availableSourcesLoading || availableSources === null }
}

export function ConnectorIconGrid({ connectors }: { connectors: SourceConfig[] }): JSX.Element | null {
    if (connectors.length === 0) {
        return null
    }

    return (
        <div className="flex flex-wrap justify-center gap-2">
            {connectors.map((connector: SourceConfig) => (
                <div
                    key={connector.name}
                    className="size-8 rounded-md border border-border bg-bg-light flex items-center justify-center"
                    title={connector.label ?? connector.name}
                >
                    <img
                        src={connector.iconPath}
                        alt={connector.label ?? connector.name}
                        className="size-5 object-contain rounded"
                    />
                </div>
            ))}
        </div>
    )
}
