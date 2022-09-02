import clsx from 'clsx'
import { range } from 'lib/utils'
import React from 'react'
import { LemonButtonProps } from '../LemonButton'
import './Skeleton.scss'

export interface SkeletonProps {
    className?: string
    width?: string | number
    height?: string | number
    repeat?: number
}

export function Skeleton({ className, width, height, repeat }: SkeletonProps): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    const content = <div className={clsx('Skeleton', className || 'h-4 w-full rounded')} style={{ width, height }} />

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

Skeleton.Text = function SkeletonText({ className, ...props }: SkeletonProps) {
    return <Skeleton className={clsx('rounded h-6 w-full', className)} {...props} />
}

Skeleton.Row = function SkeletonRow({ className, ...props }: SkeletonProps) {
    return <Skeleton className={clsx('rounded h-10 w-full', className)} {...props} />
}

Skeleton.Circle = function SkeletonCircle({ className, ...props }: SkeletonProps) {
    return <Skeleton className={clsx('rounded-full h-10 w-10 shrink-0', className)} {...props} />
}

Skeleton.Button = function SkeletonButton({
    className,
    size,
    ...props
}: SkeletonProps & { size?: LemonButtonProps['size'] }) {
    return (
        <Skeleton
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
