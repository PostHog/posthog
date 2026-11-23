import { IconCheck } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { WizardStep } from './alertWizardLogic'

interface Step {
    key: WizardStep
    label: string
}

const ALL_STEPS: Step[] = [
    { key: WizardStep.Destination, label: 'Destination' },
    { key: WizardStep.Trigger, label: 'Trigger' },
    { key: WizardStep.Configure, label: 'Configure' },
]

interface QuillAlertWizardStepperProps {
    currentStep: WizardStep
    onStepClick: (step: WizardStep) => void
    hideTriggerStep?: boolean
}

export function QuillAlertWizardStepper({
    currentStep,
    onStepClick,
    hideTriggerStep,
}: QuillAlertWizardStepperProps): JSX.Element {
    const steps = hideTriggerStep ? ALL_STEPS.filter((s) => s.key !== WizardStep.Trigger) : ALL_STEPS
    const stepOrder = new Map(steps.map((s, i) => [s.key, i]))
    const currentOrder = stepOrder.get(currentStep) ?? 0

    return (
        <nav aria-label="Alert wizard progress">
            <ol className="m-0 flex list-none flex-wrap items-center gap-1 p-0">
                {steps.map((step, index) => {
                    const order = stepOrder.get(step.key) ?? 0
                    const isCompleted = currentOrder > order
                    const isCurrent = currentStep === step.key
                    const isFuture = order > currentOrder

                    return (
                        <li key={step.key} className="flex min-w-0 items-center gap-1">
                            <Button
                                type="button"
                                variant={isCurrent ? 'primary' : 'default'}
                                onClick={() => onStepClick(step.key)}
                                disabledReason={isFuture ? 'Finish the earlier steps first' : undefined}
                                aria-current={isCurrent ? 'step' : undefined}
                            >
                                {isCompleted ? (
                                    <IconCheck className="text-success-foreground" />
                                ) : (
                                    <span className="tabular-nums">{index + 1}</span>
                                )}
                                <span className="truncate">{step.label}</span>
                            </Button>
                            {index < steps.length - 1 ? (
                                <span className="text-subtle-foreground" aria-hidden>
                                    →
                                </span>
                            ) : null}
                        </li>
                    )
                })}
            </ol>
        </nav>
    )
}
