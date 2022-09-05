import clsx from 'clsx'
import { range } from 'lib/utils'
import React from 'react'
import { LemonButtonProps } from '../LemonButton'
import './LemonSkeleton.scss'

export interface LemonSkeletonProps {
    className?: string
    width?: string | number
    height?: string | number
    repeat?: number
    active?: boolean
}

export function LemonSkeleton({ className, width, height, repeat, active = true }: LemonSkeletonProps): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    const content = (
        <div
            className={clsx('LemonSkeleton', !active && 'LemonSkeleton--static', className || 'h-4 w-full rounded')}
            style={{ width, height }}
        />
    )

    if (repeat) {
        return (
            <>
                {range(repeat).map((i) => (
                    <React.Fragment key={i}>{content}</React.Fragment>
                ))}
            </>
        )
    }
    return content
}

LemonSkeleton.Text = function LemonSkeletonText({ className, ...props }: LemonSkeletonProps) {
    return <LemonSkeleton className={clsx('rounded h-6 w-full', className)} {...props} />
}

LemonSkeleton.Row = function LemonSkeletonRow({ className, ...props }: LemonSkeletonProps) {
    return <LemonSkeleton className={clsx('rounded h-10 w-full', className)} {...props} />
}

LemonSkeleton.Circle = function LemonSkeletonCircle({ className, ...props }: LemonSkeletonProps) {
    return <LemonSkeleton className={clsx('rounded-full h-10 w-10 shrink-0', className)} {...props} />
}

LemonSkeleton.Button = function LemonSkeletonButton({
    className,
    size,
    ...props
}: LemonSkeletonProps & { size?: LemonButtonProps['size'] }) {
    return (
        <LemonSkeleton
            className={clsx(
                'rounded w-20 px-3',
                size === 'small' && 'h-10',
                (!size || size === 'medium') && 'h-10',
                className
            )}
            {...props}
        />
    )
}
