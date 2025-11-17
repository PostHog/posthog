import './LemonSkeleton.scss'

import { LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { range } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

export interface LemonSkeletonProps {
    className?: string
    /** Repeat this component this many of times */
    repeat?: number
    /** Used in combination with repeat to progressively fade out the repeated skeletons */
    fade?: boolean
    active?: boolean
}
export function LemonSkeleton({ className, repeat, active = true, fade = false }: LemonSkeletonProps): JSX.Element {
    const content = (
        <div className={cn('LemonSkeleton rounded', !active && 'LemonSkeleton--static', className || 'h-4 w-full')}>
            {/* The span is for accessibility, but also because @storybook/test-runner smoke tests require content */}
            <span>Loading…</span>
        </div>
    )

    if (repeat) {
        return (
            <>
                {range(repeat).map((i) => (
                    // eslint-disable-next-line react/forbid-dom-props
                    <div key={i} style={fade ? { opacity: 1 - i / repeat } : undefined}>
                        {content}
                    </div>
                ))}
            </>
        )
    }
    return content
}

LemonSkeleton.Text = function LemonSkeletonText({ className, ...props }: LemonSkeletonProps) {
    return <LemonSkeleton className={cn('flex-inline rounded h-6 w-full', className)} {...props} />
}

LemonSkeleton.Row = function LemonSkeletonRow({ className, ...props }: LemonSkeletonProps) {
    return <LemonSkeleton className={cn('rounded h-10 w-full', className)} {...props} />
}

LemonSkeleton.Circle = function LemonSkeletonCircle({ className, ...props }: LemonSkeletonProps) {
    return <LemonSkeleton className={cn('rounded-full shrink-0', className || 'h-10 w-10')} {...props} />
}

LemonSkeleton.Button = function LemonSkeletonButton({
    className,
    size,
    ...props
}: LemonSkeletonProps & { size?: LemonButtonProps['size'] }) {
    return (
        <LemonSkeleton
            className={cn(
                'rounded px-3',
                size === 'small' && 'h-10',
                (!size || size === 'medium') && 'h-10',
                className || 'w-20'
            )}
            {...props}
        />
    )
}
