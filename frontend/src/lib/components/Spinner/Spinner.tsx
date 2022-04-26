import clsx from 'clsx'
import React from 'react'
import './Spinner.scss'

export interface SpinnerProps {
    /** Spinner size. Small means 1rem of width */
    size?: 'sm' | 'md' | 'lg'
    /** A primary spinner is blue (most suitable for white backgrounds), while an inverse one is white (for colorful backgrounds.) */
    type?: 'primary' | 'inverse'
    /** Whether the trace of the spinner should be hidden. */
    traceless?: boolean
    style?: React.CSSProperties
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function Spinner({ size = 'md', type = 'primary', traceless = false, style }: SpinnerProps): JSX.Element {
    return (
        <svg
            className={clsx('Spinner', size && `Spinner--${size}`, type && `Spinner--${type}`)}
            style={style}
            viewBox="0 0 48 48"
            xmlns="http://www.w3.org/2000/svg"
        >
            {!traceless && <circle className="Spinner__trace" cx="24" cy="24" r="20" />}
            <circle className="Spinner__overlay" cx="24" cy="24" r="20" />
        </svg>
    )
}
