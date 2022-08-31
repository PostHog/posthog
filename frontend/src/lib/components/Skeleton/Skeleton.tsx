import clsx from 'clsx'
import React from 'react'

export interface SkeletonProps {
    className?: string
    width?: string | number
}

export function Skeleton({ className, width }: SkeletonProps): JSX.Element {
    // NOTE: this is purposefully lowercase as it is also a utility class
    // eslint-disable-next-line react/forbid-dom-props
    return <div className={clsx('skeleton', className)} style={{ width }} />
}
