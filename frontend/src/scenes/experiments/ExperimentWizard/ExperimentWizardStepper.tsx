import { IconCheckCircle } from '@posthog/icons'

import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

import { ExperimentWizardStep, STEP_ORDER } from './experimentWizardLogic'

interface Step {
    key: ExperimentWizardStep
    label: string
}

const STEPS: Step[] = [
    { key: 'about', label: 'Description' },
    { key: 'variants', label: 'Variant rollout' },
    { key: 'analytics', label: 'Analytics' },
    { key: 'implementation', label: 'Implementation' },
]

interface ExperimentWizardStepperProps {
    currentStep: ExperimentWizardStep
    onStepClick: (step: ExperimentWizardStep) => void
    stepErrors?: Record<ExperimentWizardStep, string[]>
}

export function ExperimentWizardStepper({
    currentStep,
    onStepClick,
    stepErrors,
}: ExperimentWizardStepperProps): JSX.Element {
    const currentOrder = STEP_ORDER[currentStep]

    return (
        <nav className="flex items-center" aria-label="Experiment wizard progress">
            {STEPS.map((step, index) => {
                const stepOrder = STEP_ORDER[step.key]
                const isCompleted = currentOrder > stepOrder
                const isCurrent = currentStep === step.key
                const hasErrors = (stepErrors?.[step.key]?.length ?? 0) > 0
                // Saving the draft opens the implementation step, and the form steps are done from then on
                const isSaved = currentStep === 'implementation'
                const disabledReason =
                    step.key === 'implementation'
                        ? isSaved
                            ? undefined
                            : 'Save the experiment as a draft to see its code'
                        : isSaved
                          ? 'The experiment is saved. You can change it from its page.'
                          : undefined

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
                        <Tooltip title={disabledReason}>
                            <button
                                type="button"
                                // aria-disabled rather than disabled, so the tooltip still shows on hover
                                onClick={disabledReason ? undefined : () => onStepClick(step.key)}
                                aria-disabled={!!disabledReason}
                                className={cn(
                                    'group flex items-center gap-1.5 px-2 py-1 rounded',
                                    'transition-all duration-150',
                                    'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                    disabledReason
                                        ? 'cursor-default'
                                        : 'cursor-pointer hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                                )}
                                aria-current={isCurrent ? 'step' : undefined}
                                // Other steps' labels are hidden on narrow screens, so name the button here
                                aria-label={step.label}
                            >
                                {hasErrors ? (
                                    <IconErrorOutline className="size-5 text-danger" />
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

                                <span
                                    className={cn(
                                        'text-sm whitespace-nowrap transition-colors duration-150',
                                        // Four labels don't fit a narrow column, so only the current one shows there
                                        !isCurrent && 'hidden @xl:inline',
                                        isCurrent && 'font-semibold text-primary',
                                        isCompleted && !hasErrors && 'font-medium text-primary',
                                        (!isCompleted || hasErrors) && !isCurrent && 'text-secondary'
                                    )}
                                >
                                    {step.label}
                                </span>
                            </button>
                        </Tooltip>
                    </div>
                )
            })}
        </nav>
    )
}
