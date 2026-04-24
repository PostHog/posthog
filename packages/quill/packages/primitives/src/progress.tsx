import { Progress as ProgressPrimitive } from '@base-ui/react/progress'
import * as React from 'react'

import { cn } from './lib/utils'

function Progress({ className, children, value, ...props }: ProgressPrimitive.Root.Props): React.ReactElement {
    return (
        <ProgressPrimitive.Root
            value={value}
            data-quill
            data-slot="progress"
            className={cn('flex flex-wrap gap-3', className)}
            {...props}
        >
            {children}
            <ProgressTrack>
                <ProgressIndicator />
            </ProgressTrack>
        </ProgressPrimitive.Root>
    )
}

function ProgressTrack({ className, ...props }: ProgressPrimitive.Track.Props): React.ReactElement {
    return (
        <ProgressPrimitive.Track
            className={cn('relative flex h-1 w-full items-center overflow-x-hidden rounded-md bg-input', className)}
            data-slot="progress-track"
            {...props}
        />
    )
}

function ProgressIndicator({ className, ...props }: ProgressPrimitive.Indicator.Props): React.ReactElement {
    return (
        <ProgressPrimitive.Indicator
            data-slot="progress-indicator"
            className={cn('h-full bg-primary transition-all', className)}
            {...props}
        />
    )
}

function ProgressLabel({ className, ...props }: ProgressPrimitive.Label.Props): React.ReactElement {
    return (
        <ProgressPrimitive.Label
            className={cn('text-xs/relaxed font-medium text-muted-foreground', className)}
            data-slot="progress-label"
            {...props}
        />
    )
}

function ProgressValue({ className, ...props }: ProgressPrimitive.Value.Props): React.ReactElement {
    return (
        <ProgressPrimitive.Value
            className={cn('ms-auto text-xs/relaxed text-muted-foreground tabular-nums', className)}
            data-slot="progress-value"
            {...props}
        />
    )
}

export { Progress, ProgressTrack, ProgressIndicator, ProgressLabel, ProgressValue }
