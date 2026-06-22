import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { SourceConfig } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import IconPostHog from 'public/posthog-icon.svg'
import IconHubSpot from 'public/services/hubspot.png'
import IconPostgres from 'public/services/postgres.png'
import IconSalesforce from 'public/services/salesforce.png'
import IconSnowflake from 'public/services/snowflake.png'
import IconStripe from 'public/services/stripe.png'
import IconZendesk from 'public/services/zendesk.png'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import { InlineSourceSetup } from 'products/data_warehouse/frontend/shared/components/InlineSourceSetup'

import { onboardingLogic } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { ConnectorIconGrid, DataWarehouseOnboardingLoadingPlaceholder } from './components'

// The query skeleton is fixed — SELECT, FROM, JOIN, ON stay put.
// Only the slots (comment, columns, source, posthog table, on clause,
// final clause) swap with a fade animation.
interface QueryScene {
    comment: string
    columns: string
    sourceIcon: string
    sourceName: string
    posthogTable: string
    onClause: string
    finalKeyword: string
    finalValue: string
}

const QUERY_SCENES: QueryScene[] = [
    {
        comment: '-- Which features do paying customers use most?',
        columns: 'plan_name, event, count()',
        sourceIcon: IconStripe,
        sourceName: 'stripe.subscriptions',
        posthogTable: 'posthog.events',
        onClause: 'customer_email = distinct_id',
        finalKeyword: 'GROUP BY',
        finalValue: 'plan_name, event',
    },
    {
        comment: '-- Do leads who see the demo page convert faster?',
        columns: 'lifecycle_stage, avg(days_to_close)',
        sourceIcon: IconHubSpot,
        sourceName: 'hubspot.contacts',
        posthogTable: 'posthog.sessions',
        onClause: 'email = distinct_id',
        finalKeyword: 'WHERE',
        finalValue: "$current_url LIKE '%/demo%'",
    },
    {
        comment: '-- Are power users filing fewer tickets?',
        columns: 'user_segment, count(ticket_id)',
        sourceIcon: IconZendesk,
        sourceName: 'zendesk.tickets',
        posthogTable: 'posthog.persons',
        onClause: 'requester_email = properties.email',
        finalKeyword: 'GROUP BY',
        finalValue: 'user_segment',
    },
    {
        comment: '-- Which signup source has the best close rate?',
        columns: 'initial_utm_source, sum(amount)',
        sourceIcon: IconSalesforce,
        sourceName: 'salesforce.opportunities',
        posthogTable: 'posthog.persons',
        onClause: 'email = properties.email',
        finalKeyword: 'WHERE',
        finalValue: "stage = 'Closed Won'",
    },
    {
        comment: '-- What is the avg order value by feature usage?',
        columns: 'feature_used, avg(order_total)',
        sourceIcon: IconPostgres,
        sourceName: 'app_db.orders',
        posthogTable: 'posthog.events',
        onClause: 'user_id = distinct_id',
        finalKeyword: 'GROUP BY',
        finalValue: 'feature_used',
    },
    {
        comment: '-- Which cohort drives the most revenue?',
        columns: 'cohort_name, sum(revenue)',
        sourceIcon: IconSnowflake,
        sourceName: 'warehouse.revenue',
        posthogTable: 'posthog.cohorts',
        onClause: 'user_id = person_id',
        finalKeyword: 'GROUP BY',
        finalValue: 'cohort_name',
    },
]

const QUERY_STYLES = `
    @keyframes dwh-query-fade-in {
        from { opacity: 0; transform: translateY(3px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @keyframes dwh-query-glow {
        0% { text-shadow: 0 0 12px rgba(229, 192, 123, 0.9), 0 0 24px rgba(229, 192, 123, 0.4); }
        100% { text-shadow: none; }
    }
    @keyframes dwh-query-blink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0; }
    }
    .dwh-query-slot-glow {
        animation: dwh-query-fade-in 300ms ease-out, dwh-query-glow 1.2s ease-out;
    }
    .dwh-query-slot-slide {
        animation: dwh-query-fade-in 350ms ease-out;
    }
    .dwh-query-cursor {
        display: inline-block;
        width: 2px;
        height: 1.1em;
        background: #abb2bf;
        margin-left: 2px;
        vertical-align: text-bottom;
        animation: dwh-query-blink 1s step-end infinite;
    }
    @media (prefers-reduced-motion: reduce) {
        .dwh-query-slot-glow { animation: none; }
        .dwh-query-slot-slide { animation: none; }
        .dwh-query-cursor { animation: none; opacity: 1; }
    }
`

export function DataWarehouseQueryVariant(): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <DataWarehouseOnboardingLoadingPlaceholder />
    }

    return (
        <BindLogic logic={sourceWizardLogic} props={{ availableSources }}>
            <DataWarehouseQueryInner />
        </BindLogic>
    )
}

function DataWarehouseQueryInner(): JSX.Element {
    const { goToNextStep } = useActions(onboardingLogic)
    const { reportOnboardingStepCompleted } = useActions(eventUsageLogic)
    const { availableSourcesLoading } = useValues(availableSourcesLogic)
    const { connectors } = useValues(sourceWizardLogic)
    const [phase, setPhase] = useState<'value-prop' | 'setup'>('value-prop')
    const [sceneIndex, setSceneIndex] = useState(0)

    const visibleConnectors = connectors.filter((c: SourceConfig) => !c.unreleasedSource)
    const s = QUERY_SCENES[sceneIndex]

    useEffect(() => {
        if (phase !== 'value-prop') {
            return
        }
        const timer = setInterval(() => {
            setSceneIndex((i) => (i + 1) % QUERY_SCENES.length)
        }, 4000)
        return () => clearInterval(timer)
    }, [phase])

    const handleConnectClick = (): void => {
        posthog.capture('dwh onboarding connect clicked', { variant: 'query' })
        setPhase('setup')
    }

    const handleSourceConnected = (): void => {
        posthog.capture('dwh onboarding source connected', { variant: 'query' })
        reportOnboardingStepCompleted(OnboardingStepKey.LINK_DATA)
        goToNextStep()
    }

    // Glow: used on the FROM source (the hero element that changes)
    const glowSlot = (content: React.ReactNode): JSX.Element => (
        <span key={sceneIndex} className="dwh-query-slot-glow">
            {content}
        </span>
    )
    // Slide: used on everything else that changes (comment, columns, etc.)
    const slideSlot = (content: React.ReactNode): JSX.Element => (
        <span key={sceneIndex} className="dwh-query-slot-slide">
            {content}
        </span>
    )

    return (
        <OnboardingStep
            title="Import data"
            stepKey={OnboardingStepKey.LINK_DATA}
            showContinue={false}
            showSkip={!availableSourcesLoading}
        >
            {phase === 'value-prop' ? (
                <div className="max-w-2xl mx-auto mt-4 space-y-5">
                    <style>{QUERY_STYLES}</style>

                    {/* HogQL query — fixed skeleton, animated slots */}
                    <div
                        className="rounded-xl bg-[#1d1f27] p-5 font-mono text-sm leading-loose"
                        style={{
                            border: '2.5px solid transparent',
                            backgroundClip: 'padding-box, border-box',
                            backgroundImage:
                                'linear-gradient(#1d1f27, #1d1f27), linear-gradient(135deg, #0143cb 0%, #2b6ff4 25%, #d23401 50%, #ff651f 75%, #fba000 100%)',
                            backgroundOrigin: 'border-box',
                        }}
                    >
                        {/* Comment — slide */}
                        <div className="text-[#5c6370] italic">{slideSlot(s.comment)}</div>

                        {/* SELECT — keyword static, columns slide */}
                        <div>
                            <span className="text-[#c678dd]">SELECT</span>
                            <span className="text-[#abb2bf]"> </span>
                            {slideSlot(<span className="text-[#abb2bf]">{s.columns}</span>)}
                        </div>

                        {/* FROM — keyword static, source GLOW (the hero) */}
                        <div>
                            <span className="text-[#c678dd]">FROM</span>
                            <span className="text-[#abb2bf]"> </span>
                            {glowSlot(
                                <span className="inline-flex items-center gap-1.5">
                                    <img
                                        src={s.sourceIcon}
                                        alt=""
                                        className="size-4 object-contain rounded inline-block"
                                    />
                                    <span className="text-[#e5c07b]">{s.sourceName}</span>
                                </span>
                            )}
                        </div>

                        {/* JOIN — keyword static, posthog table slide */}
                        <div>
                            <span className="text-[#c678dd]">JOIN</span>
                            <span className="text-[#abb2bf]"> </span>
                            {slideSlot(
                                <span className="inline-flex items-center gap-1.5">
                                    <img src={IconPostHog} alt="" className="size-4 inline-block" />
                                    <span className="text-[#98c379]">{s.posthogTable}</span>
                                </span>
                            )}
                        </div>

                        {/* ON — keyword static, clause slide */}
                        <div>
                            <span className="text-[#c678dd]">ON</span>
                            <span className="text-[#abb2bf]"> </span>
                            {slideSlot(<span className="text-[#abb2bf]">{s.onClause}</span>)}
                        </div>

                        {/* Final clause — slide */}
                        <div>
                            {slideSlot(
                                <>
                                    <span className="text-[#c678dd]">{s.finalKeyword}</span>
                                    <span className="text-[#abb2bf]"> {s.finalValue}</span>
                                </>
                            )}
                            <span className="dwh-query-cursor" aria-hidden="true" />
                        </div>
                    </div>

                    {/* Copy */}
                    <div className="space-y-1">
                        <h2 className="text-xl font-bold">Query your business data alongside PostHog</h2>
                        <p className="text-sm text-muted">
                            Import from your CRM, payment provider, or database and query it with HogQL — right
                            alongside your product analytics. No ETL needed.
                        </p>
                    </div>

                    {/* Source icon grid */}
                    <ConnectorIconGrid connectors={visibleConnectors} />

                    {/* CTA */}
                    <div>
                        <LemonButton
                            type="primary"
                            size="large"
                            sideIcon={<IconArrowRight />}
                            onClick={handleConnectClick}
                            data-attr="dwh-query-variant-connect-source"
                        >
                            Connect a source
                        </LemonButton>
                        <p className="text-xs text-muted mt-1">1M rows synced free every month</p>
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
                            data-attr="dwh-query-variant-back"
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
