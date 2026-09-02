import { cn } from 'lib/utils/css-classes'

import { pipClass } from './helpers'
import { InstallationStepStatus } from './installationProgressLogic'

/** One thin bar per step, colored by status — the run-at-a-glance strip on the compact surfaces. */
export function PipStrip({
    steps,
    className,
}: {
    steps: { id: string; status: InstallationStepStatus }[]
    className?: string
}): JSX.Element | null {
    if (steps.length === 0) {
        return null
    }
    return (
        <div className={cn('flex items-center gap-1 w-full', className)}>
            {steps.map((step) => (
                <span key={step.id} className={cn('h-1 flex-1 rounded-full', pipClass(step.status))} />
            ))}
        </div>
    )
}
