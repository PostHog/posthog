import './LoadingBar.scss'

import { useEffect, useState } from 'react'
import { twMerge } from 'tailwind-merge'

export interface SpinnerProps {
    textColored?: boolean
    className?: string
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function LoadingBar({ className }: SpinnerProps): JSX.Element {
    const [progress, setProgress] = useState(0)

    useEffect(() => {
        const interval = setInterval(() => {
            setProgress((prevProgress) => {
                let newProgress = prevProgress + 0.005
                if (newProgress >= 70) {
                    newProgress = prevProgress + 0.0025
                }
                if (newProgress >= 85) {
                    newProgress = prevProgress + 0.001
                }
                return newProgress
            })
        }, 50)

        return () => clearInterval(interval)
    }, []) // Empty dependency array ensures this effect runs only once

    return (
        <div className="progress-outer max-w-120 w-full my-3">
            <div className={twMerge(`progress`, className)}>
                <div
                    className="progress-bar"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: Math.round((Math.atan(progress) / (Math.PI / 2)) * 100 * 1000) / 1000 + '%' }}
                />
            </div>
        </div>
    )
}
