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

/**
 * Groups all parts of the progress bar and provides the task completion status to screen readers.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Progress](https://base-ui.com/react/components/progress)
 *
 * @baseui Progress.Root
 */
function Progress({
    className,
    children,
    value,
    variant = 'default',
    ...props
}: ProgressPrimitive.Root.Props & ProgressVariantProps): React.ReactElement {
    return (
        <ProgressPrimitive.Root
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
}

/**
 * Contains the progress bar indicator.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Progress](https://base-ui.com/react/components/progress)
 *
 * @baseui Progress.Track
 */
function ProgressTrack({ className, ...props }: ProgressPrimitive.Track.Props): React.ReactElement {
    return (
        <ProgressPrimitive.Track
            className={cn('quill-progress__track relative flex items-center', className)}
            data-slot="progress-track"
            {...props}
        />
    )
}

/**
 * Visualizes the completion status of the task.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Progress](https://base-ui.com/react/components/progress)
 *
 * @baseui Progress.Indicator
 */
function ProgressIndicator({
    className,
    variant = 'default',
    ...props
}: ProgressPrimitive.Indicator.Props & ProgressVariantProps): React.ReactElement {
    return (
        <ProgressPrimitive.Indicator
            data-slot="progress-indicator"
            data-variant={variant}
            className={cn(progressIndicatorVariants({ variant }), className)}
            {...props}
        />
    )
}

/**
 * An accessible label for the progress bar.
 * Renders a `<span>` element.
 *
 * Documentation: [Base UI Progress](https://base-ui.com/react/components/progress)
 *
 * @baseui Progress.Label
 */
function ProgressLabel({ className, ...props }: ProgressPrimitive.Label.Props): React.ReactElement {
    return (
        <ProgressPrimitive.Label
            className={cn('quill-progress__label', className)}
            data-slot="progress-label"
            {...props}
        />
    )
}

/**
 * A text element displaying the current value.
 * Renders a `<span>` element.
 *
 * Documentation: [Base UI Progress](https://base-ui.com/react/components/progress)
 *
 * @baseui Progress.Value
 */
function ProgressValue({ className, ...props }: ProgressPrimitive.Value.Props): React.ReactElement {
    return (
        <ProgressPrimitive.Value
            className={cn('quill-progress__value ms-auto', className)}
            data-slot="progress-value"
            {...props}
        />
    )
}

export { Progress, ProgressTrack, ProgressIndicator, ProgressLabel, ProgressValue, progressIndicatorVariants }
