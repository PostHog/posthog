import { DateTime } from 'luxon'

/**
 * Allowlist of path tokens we count when they appear in a navigation URL's path.
 * Order is part of the public contract — it maps 1:1 to {@link FeatureEndResult.pathTokenCounts}
 * and the corresponding ClickHouse columns. Only append; do not reorder.
 */
export const PATH_TOKEN_ALLOWLIST = [
    'login',
    'signup',
    'checkout',
    'cart',
    'billing',
    'settings',
    'account',
    'error',
    '404',
    'admin',
    'dashboard',
    'onboarding',
    'cancel',
    'refund',
] as const

export type PathToken = (typeof PATH_TOKEN_ALLOWLIST)[number]

export interface FeatureEndResult {
    startDateTime: DateTime
    endDateTime: DateTime
    eventCount: number

    // Mouse position sufficient statistics
    mousePositionCount: number
    mouseSumX: number
    mouseSumXSquared: number
    mouseSumY: number
    mouseSumYSquared: number

    // Mouse movement features
    mouseDistanceTraveled: number
    mouseDirectionChangeCount: number

    // Mouse velocity sufficient statistics
    mouseVelocitySum: number
    mouseVelocitySumOfSquares: number
    mouseVelocityCount: number

    // Scroll features
    scrollEventCount: number
    totalScrollMagnitude: number
    scrollDirectionReversalCount: number
    rapidScrollReversalCount: number
    scrollToTopCount: number

    // Click frustration features
    clickCount: number
    keypressCount: number
    mouseActivityCount: number
    rageClickCount: number
    deadClickCount: number
    backspaceCount: number

    // Inter-action timing sufficient statistics
    interActionGapCount: number
    interActionGapSumMs: number
    interActionGapSumOfSquaresMs: number
    maxIdleGapMs: number
    longIdleGapCount: number

    // Navigation features
    quickBackCount: number
    pageVisitCount: number
    visitedUrls: string[]
    pathTokenCounts: Record<PathToken, number>

    // Error features
    consoleErrorCount: number
    consoleErrorAfterClickCount: number
    consoleWarnCount: number

    // Network features
    networkRequestCount: number
    networkFailedRequestCount: number
    network4xxCount: number
    network5xxCount: number
    networkRequestDurationSum: number
    networkRequestDurationSumOfSquares: number
    networkRequestDurationCount: number

    // DOM/viewport
    mutationCount: number
    viewportResizeCount: number

    // Touch
    touchEventCount: number

    // Scroll depth
    maxScrollY: number

    // Click target diversity
    clickTargetIds: number[]

    // Form interaction diversity
    formFieldIds: number[]

    // Text selection
    textSelectionCount: number
    selectionCopyCount: number
}
