import posthog from 'posthog-js'
import { useRef, useState } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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
    const [blockedAdvanceAttempted, setBlockedAdvanceAttempted] = useState(false)
    const capturedCompletedSteps = useRef(new Set<string>())
    const step = steps[current]
    const isFirst = current === 0
    const isLast = current === steps.length - 1
    const canAdvance = step?.canAdvance !== false

    const captureCompletedSteps = (nextStepIndex: number): void => {
        for (let index = current; index < nextStepIndex; index++) {
            const completedStep = steps[index]
            if (!completedStep || capturedCompletedSteps.current.has(completedStep.key)) {
                continue
            }
            posthog.capture('alert wizard step completed', {
                step_key: completedStep.key,
                step_number: index + 1,
                next_step_key: steps[index + 1]?.key,
                total_steps: steps.length,
            })
            capturedCompletedSteps.current.add(completedStep.key)
        }
    }

    const goNext = (): void => {
        if (!canAdvance) {
            setBlockedAdvanceAttempted(true)
            onSubmitAttempted?.()
            return
        }
        setBlockedAdvanceAttempted(false)
        captureCompletedSteps(current + 1)
        setCurrent((i) => Math.min(i + 1, steps.length - 1))
    }
    const goPrev = (): void => {
        setBlockedAdvanceAttempted(false)
        setCurrent((i) => Math.max(i - 1, 0))
    }

    return (
        <div
            className="flex flex-col min-h-0 flex-1 overflow-hidden"
            onKeyDown={(event) => {
                if (
                    event.key === 'Enter' &&
                    !event.nativeEvent.isComposing &&
                    !isLast &&
                    event.target instanceof HTMLInputElement
                ) {
                    event.preventDefault()
                    goNext()
                }
            }}
        >
            <header className="border-b p-4">
                <AlertEditorHeader title={title} onBack={onBack} />
                <nav aria-label="Alert setup progress" className="mt-3">
                    <ol className="flex items-center gap-1">
                        {steps.map((s, i) => {
                            const isCurrent = i === current
                            const isComplete = i < current
                            const canAccess =
                                i <= current || steps.slice(current, i).every((st) => st.canAdvance !== false)
                            return (
                                <li key={s.key} className="flex items-center gap-1 min-w-0">
                                    <button
                                        type="button"
                                        disabled={!canAccess}
                                        onClick={() => {
                                            if (canAccess) {
                                                setBlockedAdvanceAttempted(false)
                                                if (i > current) {
                                                    captureCompletedSteps(i)
                                                }
                                                setCurrent(i)
                                            }
                                        }}
                                        className={cn(
                                            'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                                            !canAccess && 'opacity-40 cursor-not-allowed',
                                            isCurrent
                                                ? 'bg-accent text-white font-semibold'
                                                : isComplete
                                                  ? 'bg-success-highlight text-success'
                                                  : 'text-muted hover:bg-border'
                                        )}
                                        aria-current={isCurrent ? 'step' : undefined}
                                    >
                                        <span
                                            className={cn(
                                                'inline-flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold',
                                                isCurrent
                                                    ? 'bg-white text-accent'
                                                    : isComplete
                                                      ? 'bg-success text-white'
                                                      : 'border border-border'
                                            )}
                                        >
                                            {i + 1}
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
                </nav>
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
                    {blockedAdvanceAttempted && !canAdvance && step?.cannotAdvanceReason ? (
                        <span className="text-sm text-danger" role="alert">
                            {step.cannotAdvanceReason}
                        </span>
                    ) : null}
                    {isFirst ? (
                        <LemonButton type="secondary" onClick={onBack}>
                            Close
                        </LemonButton>
                    ) : (
                        <LemonButton type="secondary" icon={<IconChevronLeft />} onClick={goPrev}>
                            Back
                        </LemonButton>
                    )}
                    {!isLast ? (
                        // Stays clickable when blocked so goNext can surface the step's validation errors.
                        <LemonButton type="primary" onClick={goNext}>
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
