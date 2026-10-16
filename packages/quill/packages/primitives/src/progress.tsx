import { Progress as ProgressPrimitive } from '@base-ui/react/progress'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './progress.css'
import { cn } from './lib/utils'

const progressIndicatorVariants = cva('quill-progress__indicator', {
    variants: {
        variant: {
            default: 'quill-progress__indicator--variant-default',
            info: 'quill-progress__indicator--variant-info',
            success: 'quill-progress__indicator--variant-success',
            warning: 'quill-progress__indicator--variant-warning',
            destructive: 'quill-progress__indicator--variant-destructive',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

type ProgressVariantProps = VariantProps<typeof progressIndicatorVariants>

const Progress = React.forwardRef<
    React.ComponentRef<typeof ProgressPrimitive.Root>,
    ProgressPrimitive.Root.Props & ProgressVariantProps
>(function Progress({ className, children, value, variant = 'default', ...props }, ref) {
    return (
        <ProgressPrimitive.Root
            ref={ref}
            value={value}
            data-quill
            data-slot="progress"
            data-variant={variant}
            className={cn('flex flex-wrap gap-3', className)}
            {...props}
        >
            {children}
            <ProgressTrack>
                <ProgressIndicator variant={variant} />
            </ProgressTrack>
        </ProgressPrimitive.Root>
    )
})

const ProgressTrack = React.forwardRef<
    React.ComponentRef<typeof ProgressPrimitive.Track>,
    ProgressPrimitive.Track.Props
>(function ProgressTrack({ className, ...props }, ref) {
    return (
        <ProgressPrimitive.Track
            ref={ref}
            className={cn('quill-progress__track relative flex items-center', className)}
            data-slot="progress-track"
            {...props}
        />
    )
})

const ProgressIndicator = React.forwardRef<
    React.ComponentRef<typeof ProgressPrimitive.Indicator>,
    ProgressPrimitive.Indicator.Props & ProgressVariantProps
>(function ProgressIndicator({ className, variant = 'default', ...props }, ref) {
    return (
        <ProgressPrimitive.Indicator
            ref={ref}
            data-slot="progress-indicator"
            data-variant={variant}
            className={cn(progressIndicatorVariants({ variant }), className)}
            {...props}
        />
    )
})

const ProgressLabel = React.forwardRef<
    React.ComponentRef<typeof ProgressPrimitive.Label>,
    ProgressPrimitive.Label.Props
>(function ProgressLabel({ className, ...props }, ref) {
    return (
        <ProgressPrimitive.Label
            ref={ref}
            className={cn('quill-progress__label', className)}
            data-slot="progress-label"
            {...props}
        />
    )
})

const ProgressValue = React.forwardRef<
    React.ComponentRef<typeof ProgressPrimitive.Value>,
    ProgressPrimitive.Value.Props
>(function ProgressValue({ className, ...props }, ref) {
    return (
        <ProgressPrimitive.Value
            ref={ref}
            className={cn('quill-progress__value ms-auto', className)}
            data-slot="progress-value"
            {...props}
        />
    )
})

export { Progress, ProgressTrack, ProgressIndicator, ProgressLabel, ProgressValue, progressIndicatorVariants }
