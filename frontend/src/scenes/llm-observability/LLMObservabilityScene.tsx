import { LemonBanner, LemonTabs, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { LLMObservabilityDashboard } from './LLMObservabilityDashboard'
import { llmObservabilityLogic, LLMObservabilityTab } from './llmObservabilityLogic'
import { LLMObservabilityTraces } from './LLMObservabilityTraces'

export const scene: SceneExport = {
    component: LLMObservabilityScene,
}

const IngestionStatusCheck = (): JSX.Element | null => {
    const { hasSentAiGenerationEvent } = useValues(llmObservabilityLogic)
    if (hasSentAiGenerationEvent !== false) {
        return null
    }
    return (
        <LemonBanner type="warning" className="mt-2">
            <p>
                <strong>No LLM generation events have been detected!</strong>
            </p>
            <p>
                To use the LLM Observability product, please{' '}
                <Link to="https://posthog.com/docs/ai-engineering/observability">
                    instrument your LLM calls with the PostHog SDK
                </Link>{' '}
                (otherwise it'll be a little empty!)
            </p>
            <p>
                To get cost information, you'll also{' '}
                <Link to="/pipeline/new/transformation">need to enable the "AI Costs" transformation.</Link>
            </p>
        </LemonBanner>
    )
}

export function LLMObservabilityScene(): JSX.Element {
    const { activeTab } = useValues(llmObservabilityLogic)
    const { setActiveTab } = useActions(llmObservabilityLogic)

    return (
        <>
            <IngestionStatusCheck />
            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={[
                    {
                        key: LLMObservabilityTab.Dashboard,
                        label: 'Overview',
                        content: <LLMObservabilityDashboard />,
                    },
                    {
                        key: LLMObservabilityTab.Traces,
                        label: 'Traces',
                        content: <LLMObservabilityTraces />,
                    },
                ]}
            />
        </>
    )
}
