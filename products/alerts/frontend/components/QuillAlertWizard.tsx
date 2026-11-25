import posthog from 'posthog-js'
import { useRef, useState } from 'react'

import { IconCheck, IconChevronLeft } from '@posthog/icons'
import { Button, DialogBody, DialogFooter, DialogHeader, DialogTitle, Heading, Text } from '@posthog/quill'

import { AlertWizardProps } from './AlertWizard'
import { QuillAlertEditorActions } from './QuillAlertEditorActions'

/** Stepped alert creation layout. Render it inside a quill `DialogContent`. */
export function QuillAlertWizard({
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

    const goTo = (index: number): void => {
        setBlockedAdvanceAttempted(false)
        if (index > current) {
            captureCompletedSteps(index)
        }
        setCurrent(index)
    }

    return (
        <div
            className="contents"
            onKeyDown={(event) => {
                if (
                    event.key === 'Enter' &&
                    !event.nativeEvent.isComposing &&
                    !isLast &&
                    event.target instanceof HTMLInputElement
                ) {
                    event.preventDefault()
                    if (event.target.closest('[data-prevent-wizard-submit]')) {
                        return
                    }
                    goNext()
                }
            }}
        >
            <DialogHeader className="gap-3">
                <DialogTitle>{title}</DialogTitle>
                <nav aria-label="Alert setup progress">
                    <ol className="m-0 flex list-none flex-wrap items-center gap-1 p-0">
                        {steps.map((s, i) => {
                            const isCurrent = i === current
                            const isComplete = i < current
                            const blockingStep = steps.slice(current, i).find((st) => st.canAdvance === false)
                            const canAccess = i <= current || !blockingStep

                            return (
                                <li key={s.key} className="flex min-w-0 items-center gap-1">
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant={isCurrent ? 'primary' : 'default'}
                                        disabled={!canAccess && !blockingStep?.cannotAdvanceReason}
                                        disabledReason={canAccess ? undefined : blockingStep?.cannotAdvanceReason}
                                        onClick={() => goTo(i)}
                                        aria-current={isCurrent ? 'step' : undefined}
                                    >
                                        {isComplete ? (
                                            <IconCheck className="text-success-foreground" />
                                        ) : (
                                            <span className="tabular-nums">{i + 1}</span>
                                        )}
                                        <span className="truncate">{s.title}</span>
                                    </Button>
                                    {i < steps.length - 1 ? (
                                        <span className="text-subtle-foreground" aria-hidden>
                                            →
                                        </span>
                                    ) : null}
                                </li>
                            )
                        })}
                    </ol>
                </nav>
            </DialogHeader>
            <DialogBody>
                <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            {step?.title}
                        </Heading>
                        {step?.description ? (
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                {step.description}
                            </Text>
                        ) : null}
                    </div>
                    {step?.renderContent ? step.renderContent(blockedAdvanceAttempted) : step?.content}
                </div>
            </DialogBody>
            <DialogFooter className="flex-wrap items-center sm:justify-between">
                <div className="flex-1">{leadingActions ? leadingActions : null}</div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                    {blockedAdvanceAttempted && !canAdvance && step?.cannotAdvanceReason ? (
                        <Text size="xs" variant="destructive" role="alert" render={<span />}>
                            {step.cannotAdvanceReason}
                        </Text>
                    ) : null}
                    {isFirst ? (
                        <Button variant="outline" onClick={onBack}>
                            Close
                        </Button>
                    ) : (
                        <Button variant="outline" onClick={goPrev}>
                            <IconChevronLeft />
                            Back
                        </Button>
                    )}
                    {!isLast ? (
                        // Stays clickable when blocked so goNext can surface the step's validation errors.
                        <Button variant="primary" onClick={goNext}>
                            Continue
                        </Button>
                    ) : (
                        <QuillAlertEditorActions
                            isEditing={false}
                            isSubmitting={isSubmitting}
                            hasChanges={hasChanges}
                            onSubmitAttempted={onSubmitAttempted}
                        />
                    )}
                </div>
            </DialogFooter>
        </div>
    )
}
