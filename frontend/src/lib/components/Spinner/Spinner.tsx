import clsx from 'clsx'
import React from 'react'
import './Spinner.scss'

export interface SpinnerProps {
    size?: 'sm' | 'md' | 'lg'
    type?: 'primary' | 'inverse'
    style?: React.CSSProperties
}

export function Spinner({ size = 'md', type = 'primary', style }: SpinnerProps): JSX.Element {
    return (
        <svg
            className={clsx('spinner', size, type)}
            style={style}
            viewBox="0 0 48 48"
            xmlns="http://www.w3.org/2000/svg"
        >
            <circle className="base" cx="24" cy="24" r="20" />
            <circle className="overlay" cx="24" cy="24" r="20" />
        </svg>
    )
}
