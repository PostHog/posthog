import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SourceConfig } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'

import { OnboardingStep } from '../OnboardingStep'

export function DataWarehouseOnboardingLoadingPlaceholder(): JSX.Element {
    return (
        <OnboardingStep title="Import data" stepKey={OnboardingStepKey.LINK_DATA} showContinue={false} showSkip>
            <div className="h-64" />
        </OnboardingStep>
    )
}

// Shown when the list of sources fails to load. Without this the step falls back to the loading
// placeholder forever, leaving the user with no way forward.
export function DataWarehouseOnboardingErrorPlaceholder(): JSX.Element {
    const { load } = useActions(availableSourcesLogic)

    return (
        <OnboardingStep title="Import data" stepKey={OnboardingStepKey.LINK_DATA} showContinue={false} showSkip>
            <div className="max-w-2xl mx-auto mt-4 text-center space-y-3">
                <h2 className="text-lg font-bold">Couldn't load data sources</h2>
                <p className="text-sm text-muted">
                    Something went wrong loading the sources you can connect. Try again, or skip for now and connect a
                    source later.
                </p>
                <LemonButton type="primary" onClick={() => load()} data-attr="dwh-onboarding-retry-sources">
                    Try again
                </LemonButton>
            </div>
        </OnboardingStep>
    )
}

// An OAuth round-trip returns to this step with ?kind=<source>; start on the setup phase so
// InlineSourceSetup is mounted to resume the wizard rather than showing the value-prop screen.
export function initialOnboardingPhase(): 'value-prop' | 'setup' {
    return new URLSearchParams(window.location.search).get('kind') ? 'setup' : 'value-prop'
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
