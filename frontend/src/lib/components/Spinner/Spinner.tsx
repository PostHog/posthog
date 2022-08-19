import clsx from 'clsx'
import React from 'react'
import { IconSpinner } from '../icons'
import './Spinner.scss'

export interface SpinnerProps {
    size?: 'sm' | 'md' | 'lg'
    monocolor?: boolean
    className?: string
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function Spinner({ size = 'md', monocolor, className }: SpinnerProps): JSX.Element {
    return <IconSpinner monocolor={monocolor} className={clsx('Spinner', size && `Spinner--${size}`, className)} />
}

export function SpinnerOverlay(props: SpinnerProps): JSX.Element {
    return (
        <div className="SpinnerOverlay">
            <Spinner size="lg" {...props} />
        </div>
    )
}
