import { IconCheckCircle } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { MarketingOnboardingStep } from './marketingOnboardingLogic'

interface Step {
    key: MarketingOnboardingStep
    label: string
    optional?: boolean
}

const STEPS: Step[] = [
    { key: 'welcome', label: 'Welcome' },
    { key: 'add-source', label: 'Add source' },
    { key: 'conversion-goals', label: 'Conversion goals', optional: true },
]

const STEP_ORDER: Record<MarketingOnboardingStep, number> = {
    welcome: 0,
    'add-source': 1,
    'conversion-goals': 2,
    done: 3,
}

interface MarketingWizardStepperProps {
    currentStep: MarketingOnboardingStep
    onStepClick: (step: MarketingOnboardingStep) => void
}

export function MarketingWizardStepper({ currentStep, onStepClick }: MarketingWizardStepperProps): JSX.Element {
    const currentOrder = STEP_ORDER[currentStep]

    return (
        <nav className="flex items-center justify-center mb-6" aria-label="Marketing analytics onboarding progress">
            {STEPS.map((step, index) => {
                const stepOrder = STEP_ORDER[step.key]
                const isCompleted = currentOrder > stepOrder
                const isCurrent = currentStep === step.key

                const button = (
                    <button
                        type="button"
                        onClick={() => onStepClick(step.key)}
                        className={cn(
                            'group flex items-center gap-1.5 px-2 py-1 rounded',
                            'transition-all duration-150',
                            'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                            'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                        )}
                        aria-current={isCurrent ? 'step' : undefined}
                    >
                        {/* Indicator */}
                        {isCompleted ? (
                            <IconCheckCircle className="size-5 text-success" />
                        ) : (
                            <span
                                className={cn(
                                    'flex items-center justify-center size-5 rounded-full text-xs font-semibold',
                                    'transition-all duration-150',
                                    isCurrent && 'bg-accent text-primary-inverse ring-2 ring-accent/25',
                                    !isCurrent && 'bg-surface-secondary text-secondary border border-primary'
                                )}
                            >
                                {index + 1}
                            </span>
                        )}

                        {/* Label */}
                        <span
                            className={cn(
                                'text-sm transition-colors duration-150',
                                isCurrent && 'font-semibold text-primary',
                                isCompleted && 'font-medium text-primary',
                                !isCompleted && !isCurrent && 'text-secondary'
                            )}
                        >
                            {step.label}
                        </span>

                        {step.optional && <span className="text-xs text-tertiary">(optional)</span>}
                    </button>
                )

                return (
                    <div key={step.key} className="flex items-center">
                        {/* Connector */}
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-8 h-px transition-colors duration-150',
                                    isCompleted || isCurrent ? 'bg-success' : 'bg-border-primary'
                                )}
                            />
                        )}

                        {/* Step */}
                        {button}
                    </div>
                )
            })}
        </nav>
    )
}
