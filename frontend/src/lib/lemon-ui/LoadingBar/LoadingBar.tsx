import './LoadingBar.scss'

import { useEffect, useState } from 'react'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// atan(1) / (PI / 2) puts the frozen Storybook bar at a 50% fill
const STORYBOOK_FROZEN_PROGRESS = 1

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
    const { isVisible: isPageVisible } = usePageVisibility()
    // The 50ms ticker below moves the fill on every frame, which makes each
    // Storybook visual regression capture differ. Freeze the fill there instead.
    const frozenForStorybook = inStorybook() || inStorybookTestRunner()

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
        if (!isPageVisible || frozenForStorybook) {
            return
        }

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
    }, [loadId, isPageVisible, frozenForStorybook])

    const displayProgress = frozenForStorybook ? STORYBOOK_FROZEN_PROGRESS : _progress

    return (
        <div className={cn(`progress-outer max-w-120 w-full my-3`, wrapperClassName)} data-attr="loading-bar">
            <div className={cn(`progress`, className)}>
                <div
                    className="progress-bar"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        width: Math.round((Math.atan(displayProgress) / (Math.PI / 2)) * 100 * 1000) / 1000 + '%',
                    }}
                />
            </div>
        </div>
    )
}
