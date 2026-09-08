import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface GuidedWizardStep<Step extends string = string> {
    step: Step
    label: string
    optional?: boolean
}

export interface GuidedWizardStepperProps<Step extends string> {
    steps: GuidedWizardStep<Step>[]
    currentStep: Step
    /**
     * Where a currentStep that isn't in steps sorts: 'start' leaves every step upcoming (e.g. a
     * template picker shown before the wizard), 'end' marks every step completed (e.g. a success
     * screen shown after it). Defaults to 'start'.
     */
    unlistedStepPosition?: 'start' | 'end'
    onStepClick?: (step: Step) => void
    stepErrors?: Partial<Record<Step, string[]>>
    'aria-label'?: string
}

export function GuidedWizardStepper<Step extends string>({
    steps,
    currentStep,
    unlistedStepPosition = 'start',
    onStepClick,
    stepErrors = {},
    'aria-label': ariaLabel = 'Wizard progress',
}: GuidedWizardStepperProps<Step>): JSX.Element {
    const currentStepIndex = steps.findIndex(({ step }) => step === currentStep)
    const currentOrder = currentStepIndex >= 0 ? currentStepIndex : unlistedStepPosition === 'end' ? steps.length : -1
    const currentStepHasErrors = (stepErrors[currentStep]?.length ?? 0) > 0
    const isInteractive = !!onStepClick

    const handleStepClick = (step: Step, targetOrder: number): void => {
        // Block navigation if current step has errors (except going back)
        if (currentStepHasErrors && targetOrder > currentOrder) {
            return // Don't navigate forward when current step has errors
        }
        onStepClick?.(step)
    }

    return (
        <nav className="flex items-center" aria-label={ariaLabel}>
            {steps.map((step, index) => {
                const isCompleted = currentOrder > index
                const isCurrent = currentStep === step.step
                const hasErrors = (stepErrors[step.step]?.length ?? 0) > 0
                const isBlocked = isInteractive && currentStepHasErrors && index > currentOrder

                const button = (
                    <button
                        type="button"
                        onClick={() => handleStepClick(step.step, index)}
                        // aria-disabled instead of disabled so the button keeps pointer events (the blocked tooltip needs hover) and its tab-order slot
                        aria-disabled={isBlocked || !isInteractive}
                        className={cn(
                            'group flex items-center gap-1.5 px-2 py-1 rounded',
                            'transition-all duration-150',
                            'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                            isBlocked && 'opacity-50 cursor-not-allowed',
                            !isBlocked && isInteractive && 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]',
                            !isInteractive && 'cursor-default'
                        )}
                        aria-current={isCurrent ? 'step' : undefined}
                    >
                        {/* Indicator: errors outrank the completed checkmark, current or not */}
                        {hasErrors ? (
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
                    <div key={step.step} className="flex items-center">
                        {/* Connector */}
                        {index > 0 && (
                            <div
                                className={cn(
                                    'w-6 h-px transition-colors duration-150',
                                    hasErrors
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
