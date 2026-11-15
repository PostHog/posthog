import { IconCheckCircle, IconCircleDashed, IconClock } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { LifecycleStep, LifecycleStepState } from '../pipelineLifecycle'

const STEP_ICON: Record<LifecycleStepState, JSX.Element> = {
    done: <IconCheckCircle className="text-success shrink-0" />,
    current: <IconClock className="text-accent shrink-0" />,
    upcoming: <IconCircleDashed className="text-muted shrink-0" />,
}

const STEP_STATE_LABEL: Record<LifecycleStepState, string> = {
    done: 'Done',
    current: 'Current step',
    upcoming: 'Not yet',
}

/** Five lifecycle steps in a row. On a narrow scene the row wraps to two lines. */
export function LifecycleStrip({ steps }: { steps: LifecycleStep[] }): JSX.Element {
    return (
        <div className="@container">
            <ol className="grid grid-cols-2 @lg:grid-cols-3 @4xl:grid-cols-5 gap-2 list-none p-0 m-0">
                {steps.map((step) => (
                    <li
                        key={step.key}
                        aria-label={`${step.label}: ${STEP_STATE_LABEL[step.state]}`}
                        className={cn(
                            'flex items-start gap-2 rounded border p-2 min-w-0',
                            step.state === 'current' && 'border-accent bg-surface-secondary'
                        )}
                        data-attr={`autoresearch-lifecycle-${step.key}`}
                    >
                        <span className="text-base leading-5">{STEP_ICON[step.state]}</span>
                        <div className="flex flex-col min-w-0">
                            <span
                                className={cn('text-sm font-semibold', step.state === 'upcoming' && 'text-secondary')}
                            >
                                {step.label}
                            </span>
                            <span className="text-xs text-secondary">{step.detail}</span>
                        </div>
                    </li>
                ))}
            </ol>
        </div>
    )
}
