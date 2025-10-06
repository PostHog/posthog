import './LoadingBar.scss'

import { useEffect, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

export interface SpinnerProps {
    textColored?: boolean
    className?: string
    /** A class name for the wrapper div, useful for e.g. absolute positioning */
    wrapperClassName?: string
    // a unique id of load task that will trigger reset if changed
    loadId?: string | null
    progress?: number
    setProgress?: (loadId: string, progress: number) => void
}

/** Smoothly animated spinner for loading states. It does not indicate progress, only that something's happening. */
export function LoadingBar({ className, loadId, setProgress, progress, wrapperClassName }: SpinnerProps): JSX.Element {
    const [_progress, _setProgress] = useState(0)

    useEffect(() => {
        if (loadId && progress) {
            _setProgress(progress)
        } else {
            _setProgress(0)
        }
    }, [loadId]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (setProgress && loadId) {
            setProgress(loadId, _progress)
        }
    }, [_progress, loadId, setProgress])

    useEffect(() => {
        const interval = setInterval(() => {
            _setProgress((prevProgress) => {
                let newProgress = prevProgress + 0.005
                if (newProgress >= 70) {
                    newProgress = prevProgress + 0.0025
                }
                if (newProgress >= 85) {
                    newProgress = prevProgress + 0.001
                }
                if (newProgress >= 99) {
                    newProgress = prevProgress
                }

                return newProgress
            })
        }, 50)

        return () => clearInterval(interval)
    }, [loadId])

    return (
        <div className={cn(`progress-outer max-w-120 w-full my-3`, wrapperClassName)} data-attr="loading-bar">
            <div className={cn(`progress`, className)}>
                <div
                    className="progress-bar"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: Math.round((Math.atan(_progress) / (Math.PI / 2)) * 100 * 1000) / 1000 + '%' }}
                />
            </div>
        </div>
    )
}
