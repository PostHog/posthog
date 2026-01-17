import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

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
    stepErrors?: Partial<Record<WizardStep, string[]>>
}

export function WizardStepper({ currentStep, onStepClick, stepErrors = {} }: WizardStepperProps): JSX.Element {
    const currentOrder = STEP_ORDER[currentStep]
    const currentStepHasErrors = (stepErrors[currentStep]?.length ?? 0) > 0

    const handleStepClick = (step: WizardStep): void => {
        // Block navigation if current step has errors (except going back)
        const targetOrder = STEP_ORDER[step]
        if (currentStepHasErrors && targetOrder > currentOrder) {
            return // Don't navigate forward when current step has errors
        }
        onStepClick(step)
    }

    return (
        <nav className="flex items-center" aria-label="Survey wizard progress">
            {STEPS.map((step, index) => {
                const stepOrder = STEP_ORDER[step.key]
                const isCompleted = currentOrder > stepOrder
                const isCurrent = currentStep === step.key
                const hasErrors = (stepErrors[step.key]?.length ?? 0) > 0
                const isBlocked = currentStepHasErrors && stepOrder > currentOrder

                const button = (
                    <button
                        type="button"
                        onClick={() => handleStepClick(step.key)}
                        disabled={isBlocked}
                        className={cn(
                            'group flex items-center gap-1.5 px-2 py-1 rounded',
                            'transition-all duration-150',
                            'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                            isBlocked
                                ? 'opacity-50 cursor-not-allowed'
                                : 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                        )}
                        aria-current={isCurrent ? 'step' : undefined}
                    >
                        {/* Indicator */}
                        {hasErrors && isCurrent ? (
                            <IconWarning className="size-5 text-warning" />
                        ) : isCompleted ? (
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
                )

                return (
                    <div key={step.key} className="flex items-center">
                        {/* Connector */}
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-6 h-px transition-colors duration-150',
                                    hasErrors && isCurrent
                                        ? 'bg-warning'
                                        : isCompleted || isCurrent
                                          ? 'bg-success'
                                          : 'bg-border-primary'
                                )}
                            />
                        )}

                        {/* Step */}
                        {isBlocked ? <Tooltip title="Fix errors before proceeding">{button}</Tooltip> : button}
                    </div>
                )
            })}
        </nav>
    )
}
