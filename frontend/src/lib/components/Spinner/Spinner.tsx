import clsx from 'clsx'
import React from 'react'
import './Spinner.scss'

interface SpinnerProps {
    size?: 'sm' | 'md' | 'lg'
}

export function Spinner({ size = 'md' }: SpinnerProps): JSX.Element {
    return <div className={clsx('loader-spinner', size)} />
}
