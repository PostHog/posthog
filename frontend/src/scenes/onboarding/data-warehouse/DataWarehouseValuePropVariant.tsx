import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconGraph, IconPeople, IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { SourceConfig } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import IconPostHog from 'public/posthog-icon.svg'
import IconHubSpot from 'public/services/hubspot.png'
import IconStripe from 'public/services/stripe.png'
import IconZendesk from 'public/services/zendesk.png'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import { InlineSourceSetup } from 'products/data_warehouse/frontend/shared/components/InlineSourceSetup'

import { onboardingLogic } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { ConnectorIconGrid, DataWarehouseOnboardingLoadingPlaceholder } from './components'

const EXAMPLE_QUERIES = [
    {
        question: 'Which plan has the highest activation rate?',
        sourceIcon: IconStripe,
        sourceName: 'Stripe',
        posthogIcon: <IconGraph className="size-4" />,
        posthogLabel: 'Product analytics',
    },
    {
        question: 'Do leads who watch a demo convert faster?',
        sourceIcon: IconHubSpot,
        sourceName: 'HubSpot',
        posthogIcon: <IconRewindPlay className="size-4" />,
        posthogLabel: 'Session replay',
    },
    {
        question: 'Which support tickets come from power users?',
        sourceIcon: IconZendesk,
        sourceName: 'Zendesk',
        posthogIcon: <IconPeople className="size-4" />,
        posthogLabel: 'Cohorts',
    },
]

/**
 * Test arm for the ONBOARDING_DATA_WAREHOUSE_VALUE_PROP experiment.
 * Two-step form: step 1 sells the value of connecting external data,
 * step 2 replaces it with InlineSourceSetup.
 */
export function DataWarehouseValuePropVariant(): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <DataWarehouseOnboardingLoadingPlaceholder />
    }

    return (
        <BindLogic logic={sourceWizardLogic} props={{ availableSources }}>
            <DataWarehouseValuePropInner />
        </BindLogic>
    )
}

function DataWarehouseValuePropInner(): JSX.Element {
    const { goToNextStep } = useActions(onboardingLogic)
    const { reportOnboardingStepCompleted } = useActions(eventUsageLogic)
    const { availableSourcesLoading } = useValues(availableSourcesLogic)
    const { connectors } = useValues(sourceWizardLogic)
    const [phase, setPhase] = useState<'value-prop' | 'setup'>('value-prop')

    const visibleConnectors = connectors.filter((c: SourceConfig) => !c.unreleasedSource)

    const handleConnectClick = (): void => {
        posthog.capture('dwh onboarding connect clicked', { variant: 'table' })
        setPhase('setup')
    }

    const handleSourceConnected = (): void => {
        posthog.capture('dwh onboarding source connected', { variant: 'table' })
        reportOnboardingStepCompleted(OnboardingStepKey.LINK_DATA)
        goToNextStep()
    }

    return (
        <OnboardingStep
            title="Import data"
            stepKey={OnboardingStepKey.LINK_DATA}
            showContinue={false}
            showSkip={!availableSourcesLoading}
        >
            {phase === 'value-prop' ? (
                <div className="max-w-2xl mx-auto mt-4 space-y-5">
                    <div className="space-y-1">
                        <h2 className="text-xl font-bold">Query your business data alongside PostHog</h2>
                        <p className="text-sm text-muted">
                            Import from your CRM, payment provider, or database and join it with product analytics. No
                            ETL — PostHog syncs directly.
                        </p>
                    </div>

                    {/* Example queries table */}
                    <div className="rounded-lg border border-border overflow-hidden text-sm">
                        <div className="bg-bg-light px-3 py-1.5 border-b border-border flex items-center justify-between">
                            <span className="text-xs font-medium">Questions you can answer</span>
                            <LemonTag size="small">Examples</LemonTag>
                        </div>
                        <div className="divide-y divide-border">
                            <div className="grid grid-cols-[1fr_110px_140px] px-3 py-1.5 text-xs font-medium text-muted bg-bg-light">
                                <span>Question</span>
                                <span>Source</span>
                                <span className="flex items-center gap-1">
                                    <img src={IconPostHog} alt="" className="size-3.5" />
                                    PostHog
                                </span>
                            </div>
                            {EXAMPLE_QUERIES.map(({ question, sourceIcon, sourceName, posthogIcon, posthogLabel }) => (
                                <div key={question} className="grid grid-cols-[1fr_110px_140px] px-3 py-2 items-center">
                                    <span className="text-sm">{question}</span>
                                    <div className="flex items-center gap-1.5">
                                        <img
                                            src={sourceIcon}
                                            alt={sourceName}
                                            className="size-4 object-contain rounded shrink-0"
                                        />
                                        <span className="text-xs text-muted">{sourceName}</span>
                                    </div>
                                    <div className="flex items-center gap-1.5">
                                        <span className="shrink-0">{posthogIcon}</span>
                                        <span className="text-xs text-muted">{posthogLabel}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Source icon grid */}
                    <ConnectorIconGrid connectors={visibleConnectors} />

                    {/* CTA */}
                    <div className="flex items-center justify-between">
                        <div>
                            <LemonButton
                                type="primary"
                                size="large"
                                sideIcon={<IconArrowRight />}
                                onClick={handleConnectClick}
                                data-attr="dwh-value-prop-connect-source"
                            >
                                Connect a source
                            </LemonButton>
                            <p className="text-xs text-muted mt-1">1M rows synced free every month</p>
                        </div>
                    </div>
                </div>
            ) : (
                <div className="mt-4">
                    <div className="mb-4">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconArrowLeft />}
                            onClick={() => setPhase('value-prop')}
                            data-attr="dwh-value-prop-back"
                        >
                            Back
                        </LemonButton>
                    </div>
                    <InlineSourceSetup
                        onComplete={handleSourceConnected}
                        featured
                        title="Choose a source"
                        subtitle="You can always connect more sources later."
                    />
                </div>
            )}
        </OnboardingStep>
    )
}
