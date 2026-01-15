import { IconCheckCircle } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { WizardStep } from './surveyWizardLogic'

interface Step {
    key: WizardStep
    label: string
    optional?: boolean
}

const STEPS: Step[] = [
    { key: 'questions', label: 'Questions' },
    { key: 'where', label: 'Where' },
    { key: 'when', label: 'When' },
    { key: 'appearance', label: 'Customize', optional: true },
]

const STEP_ORDER: Record<WizardStep, number> = {
    template: -1,
    questions: 0,
    where: 1,
    when: 2,
    appearance: 3,
    success: 4,
}

interface WizardStepperProps {
    currentStep: WizardStep
    onStepClick: (step: WizardStep) => void
}

export function WizardStepper({ currentStep, onStepClick }: WizardStepperProps): JSX.Element {
    const currentOrder = STEP_ORDER[currentStep]

    return (
        <nav className="flex items-center" aria-label="Survey wizard progress">
            {STEPS.map((step, index) => {
                const stepOrder = STEP_ORDER[step.key]
                const isCompleted = currentOrder > stepOrder
                const isCurrent = currentStep === step.key

                return (
                    <div key={step.key} className="flex items-center">
                        {/* Connector */}
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-6 h-px transition-colors duration-150',
                                    isCompleted || isCurrent ? 'bg-success' : 'bg-border-primary'
                                )}
                            />
                        )}

                        {/* Step */}
                        <button
                            type="button"
                            onClick={() => onStepClick(step.key)}
                            className={cn(
                                'group flex items-center gap-1.5 px-2 py-1 rounded',
                                'transition-all duration-150',
                                'hover:bg-fill-button-tertiary-hover active:scale-[0.98]',
                                'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent'
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

                            {step.optional && <span className="text-xs text-tertiary">optional</span>}
                        </button>
                    </div>
                )
            })}
        </nav>
    )
}
