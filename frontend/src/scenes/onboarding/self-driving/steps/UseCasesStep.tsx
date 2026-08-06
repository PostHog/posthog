import { useActions } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { ONBOARDING_USE_CASES, primaryTool, toolIconType } from '../../shared/useCases'
import { productEnablementStepLogic } from '../productEnablementStepLogic'
import { useCaseSelectionLogic } from '../useCaseSelectionLogic'

/**
 * One declared use case, so the rest of the flow can drive toward it as fast as possible. Picking
 * a row advances; "set up everything" is the no-use-case path (the flow's skip, so funnels see it).
 */
export function UseCasesStep({ onContinue, onSkip }: { onContinue: () => void; onSkip: () => void }): JSX.Element {
    const { selectUseCase } = useActions(useCaseSelectionLogic)
    const { configureUseCase } = useActions(productEnablementStepLogic)

    return (
        <div className="flex flex-col gap-6 py-1">
            <div className="flex flex-col gap-3">
                {ONBOARDING_USE_CASES.map((useCase) => {
                    const iconType = toolIconType(primaryTool(useCase))
                    const colorVar = `var(--color-product-${iconType.replace(/_/g, '-')}-light)`
                    return (
                        <button
                            key={useCase.key}
                            type="button"
                            onClick={() => {
                                selectUseCase(useCase.key)
                                configureUseCase(useCase.key)
                                onContinue()
                            }}
                            className="OnboardingProductCard group flex items-center gap-4 p-4 rounded-lg border text-left cursor-pointer transition-all hover:shadow-sm"
                            // Tailwind can't parameterize the product color, so the hover border
                            // tint rides on a CSS variable the class below reads.
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
                            <div className="flex-1 flex flex-col gap-0.5">
                                <div className="font-semibold text-base">{useCase.title}</div>
                                <div className="text-sm text-secondary text-balance">{useCase.description}</div>
                            </div>
                            <IconChevronRight className="shrink-0 text-lg text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-[color:var(--goal-color)]" />
                        </button>
                    )
                })}
            </div>
            <div className="flex justify-center">
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => {
                        configureUseCase(null)
                        onSkip()
                    }}
                >
                    Not sure yet, set up everything
                </LemonButton>
            </div>
        </div>
    )
}
