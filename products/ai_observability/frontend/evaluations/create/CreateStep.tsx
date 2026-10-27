import { useEffect, useState } from 'react'

import { IconCheck, IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

/** Where a step stands: whether it is complete, and which step someone is working in. */
export interface StepProgress {
    done: boolean
    activeStep: number
    onActivate: (step: number) => void
}

/**
 * One numbered step of the new evaluation form. A line joins it to the next step, and it folds away.
 * A finished step folds by itself once someone works in a later step, and shows its summary instead.
 */
export function CreateStep({
    number,
    title,
    description,
    summary,
    done = false,
    activeStep,
    onActivate,
    action,
    children,
}: {
    number: number
    title: string
    description?: React.ReactNode
    summary?: React.ReactNode
    done?: boolean
    activeStep?: number
    onActivate?: (step: number) => void
    action?: React.ReactNode
    children?: React.ReactNode
}): JSX.Element {
    const [open, setOpen] = useState(true)
    const passed = done && activeStep !== undefined && activeStep > number
    // Fold only when someone moves past the step, so reopening it by hand keeps it open.
    useEffect(() => {
        if (passed) {
            setOpen(false)
        }
    }, [passed])
    return (
        <section
            className="group/step flex gap-3 @min-[40rem]/evaluation:gap-4 min-w-0"
            // A mouse activates the step on click, not on focus: focus comes on mousedown, and folding the steps
            // above then would move the target away before mouseup, so the click would never land.
            onFocusCapture={(event) => {
                if (event.target.matches(':focus-visible')) {
                    onActivate?.(number)
                }
            }}
            onClickCapture={() => onActivate?.(number)}
        >
            <div className="flex flex-col items-center shrink-0">
                <span
                    className={cn(
                        'flex size-7 items-center justify-center rounded-full text-sm font-semibold',
                        done ? 'bg-success-highlight text-success' : 'bg-fill-highlight-100'
                    )}
                >
                    {done ? <IconCheck /> : number}
                </span>
                <div className="w-px flex-1 bg-border mt-2 group-last/step:hidden" />
            </div>
            <div className="flex-1 min-w-0 flex flex-col gap-4 pb-8 group-last/step:pb-0">
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="flex flex-col gap-1 flex-1 basis-64 min-w-0">
                        <div className="flex items-center gap-1 -ml-1">
                            <LemonButton
                                size="xsmall"
                                icon={<IconChevronDown className={cn('transition-transform', !open && '-rotate-90')} />}
                                onClick={() => setOpen(!open)}
                                aria-label={open ? `Fold ${title}` : `Unfold ${title}`}
                                aria-expanded={open}
                            />
                            <h3 className="mb-0 text-lg font-semibold">{title}</h3>
                        </div>
                        {open
                            ? description && <p className="mb-0 text-sm text-secondary">{description}</p>
                            : summary && <p className="mb-0 text-sm text-secondary truncate">{summary}</p>}
                    </div>
                    {action}
                </div>
                {open && children}
            </div>
        </section>
    )
}
