import { IconCheck } from '@posthog/icons'
import { Dot, cn } from '@posthog/quill'

import type { WorkStepState } from './workThreadTypes'

export function WorkThreadStepMarker({ state }: { state: WorkStepState }): JSX.Element {
    return (
        <span
            aria-hidden
            className={cn(
                'flex size-6 shrink-0 items-center justify-center rounded-full border border-border',
                state === 'done' ? 'bg-completed text-completed-foreground' : 'bg-background'
            )}
        >
            {state === 'done' ? (
                <IconCheck className="size-3" />
            ) : (
                <Dot variant={state === 'needs_you' ? 'warning' : 'default'} />
            )}
        </span>
    )
}
