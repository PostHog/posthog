import clsx from 'clsx'
import React from 'react'
import './Spinner.scss'

interface SpinnerProps {
    size?: 'sm' | 'md' | 'lg'
    style?: React.CSSProperties
}

export function Spinner({ size = 'md', style }: SpinnerProps): JSX.Element {
    return <div className={clsx('loader-spinner', size)} style={style} />
}
