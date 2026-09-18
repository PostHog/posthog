import { useActions } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { ONBOARDING_USE_CASES } from '../../shared/useCases'
import { useCaseSelectionLogic } from '../useCaseSelectionLogic'

export function UseCasesStep({ onContinue, onSkip }: { onContinue: () => void; onSkip: () => void }): JSX.Element {
    const { clearUseCase, selectUseCase } = useActions(useCaseSelectionLogic)

    return (
        <div className="flex flex-col gap-4 py-1">
            {/* Use cases */}
            <div className="flex flex-col gap-3">
                {ONBOARDING_USE_CASES.map((useCase) => {
                    const iconType = useCase.icon
                    const colorVar = `var(--color-product-${iconType.replace(/_/g, '-')}-light)`

                    return (
                        <button
                            key={useCase.key}
                            type="button"
                            onClick={() => {
                                selectUseCase(useCase.key)
                                onContinue()
                            }}
                            className="OnboardingProductCard group flex items-center gap-4 p-4 rounded-lg border text-left cursor-pointer transition-all hover:shadow-sm"
                            style={{ ['--goal-color' as string]: colorVar }}
                            data-attr={`self-driving-goal-${useCase.key}`}
                        >
                            <div
                                className="size-12 shrink-0 rounded-lg flex items-center justify-center"
                                style={{ background: `color-mix(in srgb, ${colorVar} 12%, transparent)` }}
                            >
                                <div className="flex *:text-2xl group/colorful-product-icons colorful-product-icons-true">
                                    {iconForType(iconType)}
                                </div>
                            </div>

                            <div className="flex-1 flex flex-col gap-1 min-w-0">
                                <div className="font-semibold text-base">{useCase.title}</div>
                                <div className="text-sm text-secondary text-balance">{useCase.description}</div>
                            </div>

                            {/* Pick button */}
                            <div className="flex flex-row justify-center">
                                <IconArrowRight className="text-xl" />
                            </div>
                        </button>
                    )
                })}
            </div>

            {/* Continue button */}
            <div className="flex justify-center">
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => {
                        clearUseCase()
                        onSkip()
                    }}
                >
                    Continue without choosing a goal
                </LemonButton>
            </div>
        </div>
    )
}
