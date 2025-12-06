import { useActions } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { USE_CASE_OPTIONS } from 'scenes/onboarding/productRecommendations'
import { getProductIcon } from 'scenes/products/Products'
import { SceneExport } from 'scenes/sceneTypes'

import { useCaseSelectionLogic } from './useCaseSelectionLogic'

export const scene: SceneExport = {
    component: UseCaseSelection,
}

export function UseCaseSelection(): JSX.Element {
    const { selectUseCase } = useActions(useCaseSelectionLogic)

    return (
        <div className="flex flex-col items-center justify-center min-h-[calc(100vh-var(--scene-layout-header-height)-var(--scene-padding))] p-4 bg-primary">
            <div className="max-w-2xl w-full">
                <h1 className="text-4xl font-bold text-center mb-2">What do you want to do with PostHog?</h1>
                <p className="text-center text-muted mb-8">Select your primary goal to get started:</p>

                <div className="flex flex-col gap-4">
                    {USE_CASE_OPTIONS.map((useCase) => (
                        <LemonCard
                            key={useCase.key}
                            className="cursor-pointer hover:border-primary transition-colors hover:transform-none"
                            onClick={() => selectUseCase(useCase.key)}
                            hoverEffect
                        >
                            <div className="flex items-center gap-4">
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

                <div className="flex justify-end w-full mt-6">
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
