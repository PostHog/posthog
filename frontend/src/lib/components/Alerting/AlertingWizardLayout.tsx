import type { ReactNode } from 'react'

import { IconCheckCircle, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface AlertingWizardStep<T extends string = string> {
    key: T
    label: string
}

export interface AlertingWizardLayoutProps<T extends string = string> {
    steps: AlertingWizardStep<T>[]
    currentStep: T
    onStepClick: (step: T) => void
    onCancel: () => void
    children: ReactNode
    hideCloseButton?: boolean
    onSwitchToTraditional?: () => void
    traditionalEditorLabel?: string
}

export function AlertingWizardLayout<T extends string = string>({
    steps,
    currentStep,
    onStepClick,
    onCancel,
    children,
    hideCloseButton,
    onSwitchToTraditional,
    traditionalEditorLabel = 'Go back to traditional editor',
}: AlertingWizardLayoutProps<T>): JSX.Element {
    return (
        <div className="flex flex-col min-h-[400px]">
            <div className="grid grid-cols-[1fr_auto_1fr] items-center">
                <div />
                <AlertingWizardStepper steps={steps} currentStep={currentStep} onStepClick={onStepClick} />
                {hideCloseButton ? (
                    <div />
                ) : (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconX />}
                        onClick={onCancel}
                        aria-label="Close wizard"
                        className="justify-self-start ml-2"
                    />
                )}
            </div>

            <div className="max-w-lg mx-auto flex-1 w-full mt-4">{children}</div>

            {onSwitchToTraditional ? (
                <p className="text-center text-xs text-muted mt-6">
                    Need more control?{' '}
                    <button type="button" onClick={onSwitchToTraditional} className="text-link hover:underline">
                        {traditionalEditorLabel}
                    </button>
                </p>
            ) : null}
        </div>
    )
}

export interface AlertingWizardStepperProps<T extends string = string> {
    steps: AlertingWizardStep<T>[]
    currentStep: T
    onStepClick: (step: T) => void
}

export function AlertingWizardStepper<T extends string = string>({
    steps,
    currentStep,
    onStepClick,
}: AlertingWizardStepperProps<T>): JSX.Element {
    const stepOrder = new Map(steps.map((step, index) => [step.key, index]))
    const currentOrder = stepOrder.get(currentStep) ?? 0

    return (
        <nav className="flex items-center justify-center" aria-label="Alert wizard progress">
            {steps.map((step, index) => {
                const order = stepOrder.get(step.key) ?? 0
                const isCompleted = currentOrder > order
                const isCurrent = currentStep === step.key
                const isFuture = order > currentOrder

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
                            disabled={isFuture}
                            className={cn(
                                'group flex items-center gap-1.5 px-2 py-1 rounded',
                                'transition-all duration-150',
                                'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                isFuture
                                    ? 'opacity-50 cursor-not-allowed'
                                    : 'hover:bg-fill-button-tertiary-hover active:scale-[0.98]'
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
