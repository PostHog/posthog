import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface GuidedWizardStep<Step extends string = string> {
    step: Step
    label: string
    optional?: boolean
    /** Rendered as data-attr on the step button, for autocapture analytics. */
    dataAttr?: string
}

export interface GuidedWizardStepperProps<Step extends string> {
    steps: GuidedWizardStep<Step>[]
    currentStep: Step
    onStepClick?: (step: Step) => void
    stepErrors?: Partial<Record<Step, string[]>>
    /** Steps that stay in the sequence for consistent numbering but can't be navigated to, keyed to the reason why. */
    disabledSteps?: Partial<Record<Step, string>>
    className?: string
    'aria-label'?: string
}

export function GuidedWizardStepper<Step extends string>({
    steps,
    currentStep,
    onStepClick,
    stepErrors = {},
    disabledSteps = {},
    className,
    'aria-label': ariaLabel = 'Wizard progress',
}: GuidedWizardStepperProps<Step>): JSX.Element {
    // A current step outside the list (e.g. a template picker shown before the stepper) sorts before the first step
    const currentOrder = steps.findIndex(({ step }) => step === currentStep)
    const currentStepHasErrors = (stepErrors[currentStep]?.length ?? 0) > 0

    const handleStepClick = (step: Step, targetOrder: number): void => {
        // Block navigation if current step has errors (except going back)
        if (currentStepHasErrors && targetOrder > currentOrder) {
            return // Don't navigate forward when current step has errors
        }
        onStepClick?.(step)
    }

    return (
        <nav className={cn('flex items-center', className)} aria-label={ariaLabel}>
            {steps.map((step, index) => {
                const isCompleted = currentOrder > index
                const isCurrent = currentStep === step.step
                const hasErrors = (stepErrors[step.step]?.length ?? 0) > 0
                const isBlocked = currentStepHasErrors && index > currentOrder
                const disabledReason = disabledSteps[step.step]

                const button = (
                    <button
                        type="button"
                        onClick={() => !disabledReason && handleStepClick(step.step, index)}
                        // aria-disabled instead of disabled so the tooltip explaining why still shows on hover
                        disabled={isBlocked}
                        aria-disabled={isBlocked || !!disabledReason}
                        data-attr={step.dataAttr}
                        className={cn(
                            'group flex items-center gap-1.5 px-2 py-1 rounded',
                            'transition-all duration-150',
                            'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                            isBlocked
                                ? 'opacity-50 cursor-not-allowed'
                                : disabledReason
                                  ? 'opacity-50 cursor-default'
                                  : 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
                        )}
                        aria-current={isCurrent ? 'step' : undefined}
                    >
                        {/* Indicator */}
                        {hasErrors && isCurrent ? (
                            <Tooltip
                                title={stepErrors[step.step]?.map((error) => (
                                    <div key={error}>{error}</div>
                                ))}
                            >
                                <IconWarning className="size-5 text-warning" />
                            </Tooltip>
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
                    <div key={step.step} className="flex items-center">
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
                        {isBlocked ? (
                            <Tooltip title="Fix errors before proceeding">{button}</Tooltip>
                        ) : disabledReason ? (
                            <Tooltip title={disabledReason}>{button}</Tooltip>
                        ) : (
                            button
                        )}
                    </div>
                )
            })}
        </nav>
    )
}
