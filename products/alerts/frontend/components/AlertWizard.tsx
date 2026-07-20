import { useState } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { AlertEditorActions, AlertEditorHeader } from './AlertEditor'

export interface AlertWizardStep {
    key: string
    title: string
    description?: string
    /** Whether the step is safe to advance from. Buttons are disabled otherwise. */
    canAdvance?: boolean
    /** Reason shown as a tooltip when the step can't advance. */
    cannotAdvanceReason?: string
    content: React.ReactNode
}

export interface AlertWizardProps {
    title: string
    steps: AlertWizardStep[]
    isSubmitting: boolean
    hasChanges: boolean
    onBack: () => void
    onSubmitAttempted: () => void
    leadingActions?: React.ReactNode
}

/** Stepped layout for creating a new alert. Three steps (Monitor → Schedule & notify → Review)
 *  keep each screen's cognitive load low; the progress indicator shows where you are and the
 *  Review step surfaces a plain-English summary before committing. */
export function AlertWizard({
    title,
    steps,
    isSubmitting,
    hasChanges,
    onBack,
    onSubmitAttempted,
    leadingActions,
}: AlertWizardProps): JSX.Element {
    const [current, setCurrent] = useState(0)
    const step = steps[current]
    const isFirst = current === 0
    const isLast = current === steps.length - 1
    const canAdvance = step?.canAdvance !== false
    const cannotAdvanceReason = step?.cannotAdvanceReason

    const goNext = (): void => {
        if (!canAdvance) {
            onSubmitAttempted?.()
            return
        }
        setCurrent((i) => Math.min(i + 1, steps.length - 1))
    }
    const goPrev = (): void => setCurrent((i) => Math.max(i - 1, 0))

    return (
        <div className="flex flex-col min-h-0 flex-1 overflow-hidden">
            <header className="border-b p-4">
                <AlertEditorHeader title={title} onBack={onBack} />
                <ol className="flex items-center gap-1 mt-3">
                    {steps.map((s, i) => {
                        const isCurrent = i === current
                        const isComplete = i < current
                        return (
                            <li key={s.key} className="flex items-center gap-1 min-w-0">
                                <button
                                    type="button"
                                    onClick={() => setCurrent(i)}
                                    className={cn(
                                        'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors',
                                        isCurrent
                                            ? 'bg-accent-primary text-accent-primary-highlight'
                                            : isComplete
                                              ? 'bg-success-highlight text-success'
                                              : 'text-muted hover:bg-border'
                                    )}
                                    aria-current={isCurrent ? 'step' : undefined}
                                >
                                    <span
                                        className={cn(
                                            'inline-flex size-4 shrink-0 items-center justify-center rounded-full text-[10px]',
                                            isCurrent
                                                ? 'bg-accent-primary-highlight text-accent-primary'
                                                : isComplete
                                                  ? 'bg-success text-success-highlight'
                                                  : 'border border-border'
                                        )}
                                    >
                                        {isComplete ? '✓' : i + 1}
                                    </span>
                                    <span className="truncate">{s.title}</span>
                                </button>
                                {!isLastStep(i, steps) ? (
                                    <span className="text-border" aria-hidden>
                                        →
                                    </span>
                                ) : null}
                            </li>
                        )
                    })}
                </ol>
            </header>
            <section className="p-4 min-h-0 flex-1 overflow-y-auto">
                <div className="space-y-1 mb-3">
                    <h3 className="text-base font-semibold m-0">{step?.title}</h3>
                    {step?.description ? <p className="text-xs text-secondary m-0">{step.description}</p> : null}
                </div>
                {step?.content}
            </section>
            <footer className="flex flex-wrap items-center justify-between gap-2 border-t p-4">
                <div className="flex-1">{leadingActions ? leadingActions : null}</div>
                <div className="flex items-center gap-2">
                    <LemonTag type="default" className="m-0">
                        Step {current + 1} of {steps.length}
                    </LemonTag>
                    {!isFirst ? (
                        <LemonButton type="secondary" icon={<IconChevronLeft />} onClick={goPrev}>
                            Back
                        </LemonButton>
                    ) : null}
                    {!isLast ? (
                        <LemonButton
                            type="primary"
                            onClick={goNext}
                            disabledReason={canAdvance ? undefined : cannotAdvanceReason}
                        >
                            Continue
                        </LemonButton>
                    ) : (
                        <AlertEditorActions
                            isEditing={false}
                            isSubmitting={isSubmitting}
                            hasChanges={hasChanges}
                            onSubmitAttempted={onSubmitAttempted}
                        />
                    )}
                </div>
            </footer>
        </div>
    )
}

function isLastStep(index: number, steps: AlertWizardStep[]): boolean {
    return index === steps.length - 1
}
