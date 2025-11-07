import { useActions } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { getProductIcon } from 'scenes/products/Products'
import { SceneExport } from 'scenes/sceneTypes'

import { useCaseSelectionLogic } from './useCaseSelectionLogic'

export const scene: SceneExport = {
    component: UseCaseSelection,
}

const USE_CASES = [
    {
        key: 'see_user_behavior',
        iconKey: 'IconGraph',
        iconColor: 'rgb(47 128 250)',
        title: 'See what users are doing',
        description: 'Track behavior, analyze trends, understand your audience',
    },
    {
        key: 'fix_issues',
        iconKey: 'IconRewindPlay',
        iconColor: 'rgb(247 165 1)',
        title: 'Find and fix issues',
        description: 'Debug problems, track errors, investigate user issues',
    },
    {
        key: 'launch_features',
        iconKey: 'IconToggle',
        iconColor: 'rgb(48 171 198)',
        title: 'Launch features with confidence',
        description: 'Control rollouts, run experiments, measure impact',
    },
    {
        key: 'collect_feedback',
        iconKey: 'IconMessage',
        iconColor: 'rgb(243 84 84)',
        title: 'Collect user feedback',
        description: 'Run surveys and gather insights from users',
    },
    {
        key: 'monitor_ai',
        iconKey: 'IconLlmAnalytics',
        iconColor: 'rgb(182 42 217)',
        title: 'Monitor AI applications',
        description: 'Track LLM performance, costs, and quality',
    },
]

export function UseCaseSelection(): JSX.Element {
    const { selectUseCase } = useActions(useCaseSelectionLogic)

    return (
        <div className="flex flex-col items-center justify-center min-h-screen p-4 bg-primary">
            <div className="max-w-2xl w-full">
                <h1 className="text-4xl font-bold text-center mb-2">What do you want to do with PostHog?</h1>
                <p className="text-center text-muted mb-8">Select your primary goal to get started:</p>

                <div className="flex flex-col gap-4">
                    {USE_CASES.map((useCase) => (
                        <LemonCard
                            key={useCase.key}
                            className="cursor-pointer hover:border-primary transition-colors hover:transform-none"
                            onClick={() => selectUseCase(useCase.key as any)}
                            hoverEffect
                        >
                            <div className="flex items-start gap-4">
                                <div className="text-3xl flex-shrink-0">
                                    {getProductIcon(useCase.iconColor, useCase.iconKey, 'text-3xl')}
                                </div>
                                <div className="flex-1">
                                    <h3 className="font-semibold mb-1">{useCase.title}</h3>
                                    <p className="text-muted text-sm mb-0">{useCase.description}</p>
                                </div>
                            </div>
                        </LemonCard>
                    ))}
                </div>

                <div className="text-center mt-6">
                    <button
                        className="text-muted hover:text-default text-sm"
                        onClick={() => selectUseCase('pick_myself')}
                    >
                        I want to pick products myself →
                    </button>
                </div>
            </div>
        </div>
    )
}
