import clsx from 'clsx'
import { useEffect, useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { MetricRetryInfo } from '~/scenes/experiments/experimentMetricsLogic'

/** Placeholder until the background recalculation doc ships; nothing here changes when it does. */
export const RECALCULATION_RETRY_DOCS_URL = 'https://posthog.com/docs/experiments/background-recalculation'

const RETRY_REASONS: Record<string, string> = {
    rate_limited: 'The ClickHouse cluster is busy right now.',
    timeout: 'The query took too long to complete.',
    out_of_memory: 'The query ran out of memory.',
    server_error: 'Something went wrong while computing this metric.',
}

export function retryReason(errorType: string): string {
    return RETRY_REASONS[errorType] ?? RETRY_REASONS.server_error
}

function countdownLabel(target: string | null | undefined): string {
    if (!target) {
        return 'shortly'
    }
    const seconds = Math.round((new Date(target).getTime() - Date.now()) / 1000)
    if (seconds <= 0) {
        return 'any moment now'
    }
    if (seconds < 90) {
        return `in ${seconds}s`
    }
    return dayjs().to(dayjs(target))
}

/**
 * Human-readable countdown to an estimated retry ("in 45s", "in 3 minutes", "any moment now"),
 * ticking every second. The estimate comes from the backend's retry schedule; worker pickup adds
 * slack after it passes, hence "any moment now" rather than flipping to an error.
 */
export function useRetryCountdownLabel(target: string | null | undefined): string {
    const [label, setLabel] = useState<string>(() => countdownLabel(target))
    useEffect(() => {
        setLabel(countdownLabel(target))
        if (!target) {
            return
        }
        const intervalId = setInterval(() => setLabel(countdownLabel(target)), 1000)
        return () => clearInterval(intervalId)
    }, [target])
    return label
}

/** The full retry explanation: reason, the server error that triggered it, counter, countdown, help link.
 * Shared between the chart-cell state and the metric header tag's popover. */
export function MetricRetryDetails({ retry, className }: { retry: MetricRetryInfo; className?: string }): JSX.Element {
    const countdown = useRetryCountdownLabel(retry.next_retry_at)
    return (
        <div className={clsx('flex flex-col gap-0.5', className)}>
            <div className="flex items-center gap-1.5 text-xs font-medium">
                <Spinner textColored className="text-accent" />
                <span>{retryReason(retry.error_type)}</span>
            </div>
            {retry.message && (
                <div className="text-muted text-xs italic line-clamp-2" title={retry.message}>
                    {retry.message}
                </div>
            )}
            <div className="text-muted text-xs">
                Retry {retry.attempt} of {retry.max_attempts} · next attempt {countdown} ·{' '}
                {/* <Link to={RECALCULATION_RETRY_DOCS_URL} target="_blank">
                    Why do we retry?
                </Link> */}
            </div>
        </div>
    )
}

export function MetricRetryState({ retry }: { retry: MetricRetryInfo }): JSX.Element {
    return (
        <div className="flex h-full items-center justify-center px-3">
            <MetricRetryDetails retry={retry} className="items-center text-center" />
        </div>
    )
}
