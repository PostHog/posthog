import posthog from 'posthog-js'
import type { ErrorInfo } from 'react'

/** `onError` handler for hog-charts trends adapters. Captures the React error
 *  boundary's error/info to PostHog, tagged with the chart `feature` name. */
export function makeChartErrorHandler(feature: string): (error: Error, info: ErrorInfo) => void {
    return (error, info) => {
        posthog.captureException(error, {
            feature,
            componentStack: info.componentStack ?? undefined,
        })
    }
}
