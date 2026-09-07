import { useEffect, useState } from 'react'

import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

/** After this long, a load stops being a spinner and starts explaining itself. */
export const SLOW_LOAD_THRESHOLD_SECONDS = 15

/** Seconds since the current load started. Resets when a new load begins. */
export function useElapsedSeconds(isLoading: boolean): number {
    const [seconds, setSeconds] = useState(0)

    useEffect(() => {
        if (!isLoading) {
            setSeconds(0)
            return
        }
        const startedAt = Date.now()
        // Recomputed from the start time, so a throttled background tab still shows the real elapsed time.
        const tick = (): void => setSeconds(Math.floor((Date.now() - startedAt) / 1000))
        tick()
        const intervalId = setInterval(tick, 1000)
        return () => clearInterval(intervalId)
    }, [isLoading])

    return seconds
}

function formatElapsedSeconds(seconds: number): string {
    return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, '0')}`
}

/**
 * Replaces the plain spinner once a load passes the threshold: how long it has run, and the query
 * debugger link that otherwise appears only after the load fails.
 */
export function MetricSlowLoadState({ seconds, query }: { seconds: number; query?: Record<string, any> }): JSX.Element {
    return (
        <div className="flex h-full flex-col items-center justify-center gap-0.5 px-3 text-center">
            <div className="flex items-center gap-1.5 text-xs font-medium">
                <Spinner textColored className="text-accent" />
                <span>Still loading results ({formatElapsedSeconds(seconds)})</span>
            </div>
            <div className="text-muted text-xs">
                Metrics over a lot of data can take a few minutes.
                {query && (
                    <>
                        {' '}
                        <Link to={urls.debugQuery(query)}>Open in query debugger</Link>
                    </>
                )}
            </div>
        </div>
    )
}

interface ChartLoadingStateProps {
    height: number
    query?: Record<string, any>
}

export function ChartLoadingState({ height, query }: ChartLoadingStateProps): JSX.Element {
    const seconds = useElapsedSeconds(true)

    return (
        <div
            className="flex items-center justify-center gap-2 text-[14px] font-normal"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: `${height}px` }}
        >
            {seconds >= SLOW_LOAD_THRESHOLD_SECONDS ? (
                <MetricSlowLoadState seconds={seconds} query={query} />
            ) : (
                <>
                    <Spinner className="text-lg" />
                    <span>Loading results&hellip;</span>
                </>
            )}
        </div>
    )
}
