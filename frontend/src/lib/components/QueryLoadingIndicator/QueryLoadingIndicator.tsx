import { useEffect, useState } from 'react'
import { TextMorph } from 'torph/react'

import { dayjs } from 'lib/dayjs'
import { holidaysMatcher } from 'lib/holidays'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { humanFriendlyNumber, humanizeBytes, inStorybook, inStorybookTestRunner } from 'lib/utils'

import { QueryStatus } from '~/queries/schema/schema-general'

// Loading messages from EmptyStates.tsx
const BASE_LOADING_MESSAGES = [
    'Snuffling through spiky piles for insights…',
    'Counting quills, clicks, and insights…',
    'Scurrying through the underbrush for insights…',
    'Hoarding shiny little bits of insights…',
    'Padding softly through fields of insights…',
    'Untangling prickly paths to insights…',
    'Balancing nuts, berries, and insights…',
]

const CHRISTMAS_LOADING_MESSAGES = [
    'Wrapping up cozy bundles of insights…',
    'Dashing through snowy trails for insights…',
    'Stringing twinkly lights around insights…',
    'Jingling tiny bells for insights…',
    'Sleighing through frosty fields of insights…',
    'Warming chilly paws with festive insights…',
]

const HALLOWEEN_LOADING_MESSAGES = [
    'Whispering through shadowy trails for insights…',
    'Summoning mysterious clouds of insights…',
    'Stirring a bubbling cauldron of insights…',
    'Creeping through moonlit patches for insights…',
    'Enchanting unsuspecting bits of insights…',
    'Shuffling through haunted heaps of insights…',
]

const LOADING_MESSAGES = holidaysMatcher(
    {
        christmas: CHRISTMAS_LOADING_MESSAGES,
        halloween: HALLOWEEN_LOADING_MESSAGES,
    },
    BASE_LOADING_MESSAGES
)

export interface QueryLoadingIndicatorProps {
    /** Query ID for progress tracking */
    queryId?: string | null
    /** Poll response with query status */
    pollResponse?: Record<string, QueryStatus | null> | null
    /** Whether to show loading details (rows, bytes, etc.) */
    showDetails?: boolean
    /** Whether results are cached (shows subtle loading bar instead of full state) */
    hasCachedResults?: boolean
    /** Height for the loading state container (in pixels) */
    height?: number
    /** Custom suggestion element to display */
    suggestion?: JSX.Element
    /** Progress value (0-100) */
    progress?: number
    /** Progress setter callback */
    setProgress?: (loadId: string, progress: number) => void
}

export function QueryLoadingIndicator({
    queryId,
    pollResponse,
    showDetails = true,
    hasCachedResults = false,
    height,
    suggestion,
    progress,
    setProgress,
}: QueryLoadingIndicatorProps): JSX.Element {
    const [rowsRead, setRowsRead] = useState(0)
    const [bytesRead, setBytesRead] = useState(0)
    const [secondsElapsed, setSecondsElapsed] = useState(0)
    const [loadingMessageIndex, setLoadingMessageIndex] = useState(() =>
        inStorybook() || inStorybookTestRunner() ? 0 : Math.floor(Math.random() * LOADING_MESSAGES.length)
    )
    const { isVisible: isPageVisible } = usePageVisibility()

    // Update rows/bytes read from poll response
    useEffect(() => {
        if (!isPageVisible || !showDetails) {
            return
        }

        const status = pollResponse?.status?.query_progress
        const previousStatus = pollResponse?.previousStatus?.query_progress
        setRowsRead(previousStatus?.rows_read || 0)
        setBytesRead(previousStatus?.bytes_read || 0)

        const interval = setInterval(() => {
            setRowsRead((rowsRead) => {
                const diff = (status?.rows_read || 0) - (previousStatus?.rows_read || 0)
                return Math.min(rowsRead + diff / 30, status?.rows_read || 0)
            })
            setBytesRead((bytesRead) => {
                const diff = (status?.bytes_read || 0) - (previousStatus?.bytes_read || 0)
                return Math.min(bytesRead + diff / 30, status?.bytes_read || 0)
            })
            setSecondsElapsed(() => {
                return dayjs().diff(dayjs(pollResponse?.status?.start_time), 'milliseconds')
            })
        }, 100)

        return () => clearInterval(interval)
    }, [pollResponse, isPageVisible, showDetails])

    // Toggle loading messages every 3-5 seconds
    useEffect(() => {
        if (!isPageVisible || hasCachedResults || inStorybook() || inStorybookTestRunner()) {
            return
        }

        const TOGGLE_INTERVAL_MIN = 3000
        const TOGGLE_INTERVAL_JITTER = 2000

        const interval = setInterval(
            () => {
                setLoadingMessageIndex((current) => {
                    let newIndex = Math.floor(Math.random() * LOADING_MESSAGES.length)
                    if (newIndex === current) {
                        newIndex = (newIndex + 1) % LOADING_MESSAGES.length
                    }
                    return newIndex
                })
            },
            TOGGLE_INTERVAL_MIN + Math.random() * TOGGLE_INTERVAL_JITTER
        )

        return () => clearInterval(interval)
    }, [isPageVisible, hasCachedResults])

    // If we have cached results, show only a subtle loading bar
    if (hasCachedResults) {
        return (
            <div className="w-full" style={height ? { height: `${height}px` } : undefined}>
                <LoadingBar loadId={queryId} progress={progress} setProgress={setProgress} />
            </div>
        )
    }

    // Full loading state with messages and details
    const bytesPerSecond = (bytesRead / (secondsElapsed || 1)) * 1000
    const estimatedRows = pollResponse?.status?.query_progress?.estimated_rows_total
    const cpuUtilization =
        (pollResponse?.status?.query_progress?.active_cpu_time || 0) /
        (pollResponse?.status?.query_progress?.time_elapsed || 1) /
        10000

    const suggestions = suggestion || (
        <div className="flex gap-3">
            <p className="text-xs m-0">Need to speed things up? Try reducing the date range.</p>
        </div>
    )

    return (
        <div
            data-attr="query-loading-indicator"
            className="flex flex-col gap-1 rounded px-4 py-6 w-full justify-center items-center"
            style={height ? { height: `${height}px` } : undefined}
        >
            <TextMorph as="span" className="font-semibold mb-1 text-center">
                {LOADING_MESSAGES[loadingMessageIndex]}
            </TextMorph>

            <div className="flex flex-col gap-2 justify-center items-center max-w-120">
                <LoadingBar loadId={queryId} progress={progress} setProgress={setProgress} />
                {suggestions}
                {showDetails && (
                    <>
                        <p className="mx-auto text-center text-xs">
                            {rowsRead > 0 && bytesRead > 0 && (
                                <>
                                    <span>{humanFriendlyNumber(rowsRead || 0, 0)} </span>
                                    <span>
                                        {estimatedRows && estimatedRows >= rowsRead ? (
                                            <span>/ {humanFriendlyNumber(estimatedRows)} </span>
                                        ) : null}
                                    </span>
                                    <span>rows</span>
                                    <br />
                                    <span>{humanizeBytes(bytesRead || 0)} </span>
                                    <span>({humanizeBytes(bytesPerSecond || 0)}/s)</span>
                                    <br />
                                    <span>CPU {humanFriendlyNumber(cpuUtilization, 0)}%</span>
                                </>
                            )}
                        </p>
                        {queryId && (
                            <div className="text-muted text-xs">
                                Query ID: <span className="font-mono">{queryId}</span>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}
