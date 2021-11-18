import clsx from 'clsx'
import React from 'react'
import './Spinner.scss'

interface SpinnerProps {
    size?: 'sm' | 'md' | 'lg'
    type?: 'primary' | 'inverse'
    style?: React.CSSProperties
}

export function Spinner({ size = 'md', type = 'primary', style }: SpinnerProps): JSX.Element {
    return <div className={clsx('loader-spinner', size, type)} style={style} />
}
