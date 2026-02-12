import { IconCheckCircle } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { ExperimentWizardStep } from './experimentWizardLogic'

interface Step {
    key: ExperimentWizardStep
    label: string
}

const STEPS: Step[] = [
    { key: 'about', label: 'Description' },
    { key: 'variants', label: 'Variant rollout' },
    { key: 'analytics', label: 'Analytics' },
]

const STEP_ORDER: Record<ExperimentWizardStep, number> = {
    about: 0,
    variants: 1,
    analytics: 2,
}

interface ExperimentWizardStepperProps {
    currentStep: ExperimentWizardStep
    onStepClick: (step: ExperimentWizardStep) => void
}

export function ExperimentWizardStepper({ currentStep, onStepClick }: ExperimentWizardStepperProps): JSX.Element {
    const currentOrder = STEP_ORDER[currentStep]

    return (
        <nav className="flex items-center" aria-label="Experiment wizard progress">
            {STEPS.map((step, index) => {
                const stepOrder = STEP_ORDER[step.key]
                const isCompleted = currentOrder > stepOrder
                const isCurrent = currentStep === step.key

                return (
                    <div key={step.key} className="flex items-center">
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-6 h-px transition-colors duration-150',
                                    isCompleted || isCurrent ? 'bg-success' : 'bg-border-primary'
                                )}
                            />
                        )}
                        <button
                            type="button"
                            onClick={() => onStepClick(step.key)}
                            className={cn(
                                'group flex items-center gap-1.5 px-2 py-1 rounded',
                                'transition-all duration-150',
                                'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                'cursor-pointer hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                            )}
                            aria-current={isCurrent ? 'step' : undefined}
                        >
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
                        </button>
                    </div>
                )
            })}
        </nav>
    )
}
