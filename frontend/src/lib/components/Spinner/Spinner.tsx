import clsx from 'clsx'
import React from 'react'
import { IconSpinner } from '../icons'
import './Spinner.scss'

export interface SpinnerProps {
    size?: 'sm' | 'md' | 'lg'
    className?: string
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function Spinner({ size = 'md', className }: SpinnerProps): JSX.Element {
    return <IconSpinner className={clsx('Spinner', size && `Spinner--${size}`, className)} />
}
