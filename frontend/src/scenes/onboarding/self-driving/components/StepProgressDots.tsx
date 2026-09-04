import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

interface StepProgressDotsProps {
    steps: { id: string; label: string }[]
    currentIndex: number
    /** Index of the furthest step the user reached. Everything up to it is navigable. */
    furthestIndex: number
    onSelect: (index: number) => void
}

/** The onboarding progress dots. A dot for a step the user already reached takes them to it, in
 * either direction, so a wrong turn costs one click rather than the whole sequence. */
export function StepProgressDots({ steps, currentIndex, furthestIndex, onSelect }: StepProgressDotsProps): JSX.Element {
    return (
        <div
            className="absolute left-1/2 -translate-x-1/2 flex items-center gap-1.5"
            role="group"
            aria-label={`Step ${currentIndex + 1} of ${steps.length}`}
        >
            {steps.map((step, index) => {
                const isCurrent = index === currentIndex
                const isReached = index <= furthestIndex
                const dot = (
                    <span
                        className={cn(
                            'block h-1.5 rounded-full transition-all',
                            isCurrent
                                ? 'w-6 bg-accent'
                                : isReached
                                  ? 'w-1.5 bg-accent opacity-40 group-hover:opacity-100'
                                  : 'w-1.5 bg-border'
                        )}
                    />
                )
                if (isCurrent || !isReached) {
                    return (
                        <span key={step.id} aria-current={isCurrent ? 'step' : undefined}>
                            {dot}
                        </span>
                    )
                }
                return (
                    <Tooltip key={step.id} title={step.label}>
                        {/* Padding gives the 6px dot a pointer-sized target without changing the
                            row's height. */}
                        <button
                            type="button"
                            onClick={() => onSelect(index)}
                            aria-label={`Go to ${step.label}`}
                            className="group flex items-center px-1 py-2 -mx-1 -my-2 cursor-pointer"
                            data-attr="self-driving-onboarding-step-dot"
                        >
                            {dot}
                        </button>
                    </Tooltip>
                )
            })}
        </div>
    )
}
