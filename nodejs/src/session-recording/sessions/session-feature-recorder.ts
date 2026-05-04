import crypto from 'crypto'
import { DateTime } from 'luxon'

import { defaultConfig } from '../../config/config'
import { ParsedMessageData, SnapshotEvent } from '../kafka/types'
import { RRWebEventSource, RRWebEventType, hrefFrom, isClick, isKeypress, isMouseActivity } from '../rrweb-types'

const POSTHOG_NETWORK_PLUGIN = 'posthog/network@1'
const RRWEB_NETWORK_PLUGIN = 'rrweb/network@1'

const POSTHOG_NETWORK_DURATION_KEY = 39
const POSTHOG_NETWORK_STATUS_KEY = 21

export const MAX_UNIQUE_VALUES = 1000

export const md5Hex = (s: string): string => crypto.createHash('md5').update(s).digest('hex')

interface RRWebEventData {
    type?: number
    timestamp: number
    data?: {
        source?: number
        type?: number
        x?: number
        y?: number
        id?: number
        positions?: Array<{ x: number; y: number; id: number; timeOffset: number }>
        plugin?: string
        payload?: {
            level?: string
            requests?: Array<{
                duration?: number
                status?: number
                responseStatus?: number
            }>
            [key: number]: unknown
        }
    }
}

/**
 * Per-batch ML features extracted from RRWEB data.
 *
 * FEATURES
 *
 * Session duration: max_last_timestamp - min_first_timestamp (seconds)
 *
 * Additive counters (Note: divide by session duration for rate):
 *   - event_count
 *   - click_count
 *   - keypress_count
 *   - mouse_activity_count
 *   - rage_click_count
 *   - dead_click_count
 *   - scroll_event_count
 *   - quick_back_count
 *   - page_visit_count
 *   - console_error_count
 *   - console_error_after_click_count
 *   - network_request_count
 *   - network_failed_request_count
 *   - text_selection_count
 *
 * Max aggregates:
 *   - max_idle_gap_ms
 *   - max_scroll_y
 *
 * Sufficient statistics:
 *   - Mouse position mean:    mouse_sum_x / mouse_position_count
 *   - Mouse position stddev:  sqrt(mouse_sum_x_squared / mouse_position_count - (mouse_sum_x / mouse_position_count)^2)
 *   - Mouse velocity mean:    mouse_velocity_sum / mouse_velocity_count
 *   - Mouse velocity stddev:  sqrt(mouse_velocity_sum_of_squares / mouse_velocity_count - (mouse_velocity_sum / mouse_velocity_count)^2)
 *   - Inter-action gap mean:  inter_action_gap_sum_ms / inter_action_gap_count
 *   - Inter-action gap stddev: sqrt(inter_action_gap_sum_of_squares_ms / inter_action_gap_count - (inter_action_gap_sum_ms / inter_action_gap_count)^2)
 *   - Network duration mean:  network_request_duration_sum / network_request_duration_count
 *   - Network duration stddev: sqrt(network_request_duration_sum_of_squares / network_request_duration_count - (network_request_duration_sum / network_request_duration_count)^2)
 *   - Scroll magnitude/event: total_scroll_magnitude / scroll_event_count
 *   - Mouse direction change rate: mouse_direction_change_count / mouse_distance_traveled
 *
 * Set-based metrics:
 *   - Unique click targets:   uniqExactMerge(unique_click_target_count)
 *   - Unique URLs visited:    uniqExactMerge(unique_url_count) — visited_urls are md5-hashed at the source
 *   - Page revisit count:     page_visit_count - uniqExactMerge(unique_url_count)
 *
 * All sets are capped at MAX_UNIQUE_VALUES per batch to bound payload size < 50 KB.
 */
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

    // Click frustration features
    clickCount: number
    keypressCount: number
    mouseActivityCount: number
    rageClickCount: number
    deadClickCount: number

    // Inter-action timing sufficient statistics
    interActionGapCount: number
    interActionGapSumMs: number
    interActionGapSumOfSquaresMs: number
    maxIdleGapMs: number

    // Navigation features
    quickBackCount: number
    pageVisitCount: number
    visitedUrls: string[]

    // Error features
    consoleErrorCount: number
    consoleErrorAfterClickCount: number

    // Network features
    networkRequestCount: number
    networkFailedRequestCount: number
    networkRequestDurationSum: number
    networkRequestDurationSumOfSquares: number
    networkRequestDurationCount: number

    // Scroll depth
    maxScrollY: number

    // Click target diversity
    clickTargetIds: number[]

    // Text selection
    textSelectionCount: number
}

/**
 * Extracts aggregate features from session recording events for ML scoring.
 */
export class SessionFeatureRecorder {
    private ended = false
    private _distinctId: string | null = null
    private _run: boolean = false

    private eventCount: number = 0
    private endDateTime: DateTime | null = null
    private startDateTime: DateTime | null = null
    private clickCount: number = 0
    private keypressCount: number = 0
    private mouseActivityCount: number = 0

    // Mouse movement features
    private mousePositionCount = 0
    private mouseSumX = 0
    private mouseSumXSquared = 0
    private mouseSumY = 0
    private mouseSumYSquared = 0
    private mouseDistanceTraveled = 0
    private mouseDirectionChangeCount = 0
    private lastMouseX: number | null = null
    private lastMouseY: number | null = null
    private lastMouseDx: number | null = null
    private lastMouseDy: number | null = null
    private mouseVelocitySum = 0
    private mouseVelocitySumOfSquares = 0
    private mouseVelocityCount = 0
    private lastMouseTimestamp: number | null = null

    // Scroll features
    private scrollEventCount = 0
    private totalScrollMagnitude = 0
    private scrollDirectionReversalCount = 0
    private rapidScrollReversalCount = 0
    private lastScrollDirection: 'up' | 'down' | null = null
    private lastScrollTimestamp: number | null = null
    private lastScrollY: number | null = null
    private lastScrollId: number | null = null

    // Click frustration features
    private rageClickCount = 0
    private deadClickCount = 0
    private lastClickTimestamp: number | null = null
    private lastClickX: number | null = null
    private lastClickY: number | null = null
    private consecutiveClickCount = 0
    private urlChangedSinceLastClick = false

    // Inter-action timing sufficient statistics
    private lastActionTimestamp: number | null = null
    private interActionGapCount = 0
    private interActionGapSumMs = 0
    private interActionGapSumOfSquaresMs = 0
    private maxIdleGapMs = 0

    // Navigation features
    private quickBackCount = 0
    private pageVisitCount = 0
    private visitedUrls: Set<string> = new Set()
    private lastNavigationTimestamp: number | null = null
    private lastNavigationUrl: string | null = null

    // Error features
    private consoleErrorCount = 0
    private consoleErrorAfterClickCount = 0
    private lastUserActionTimestamp: number | null = null

    // Network features
    private networkRequestCount = 0
    private networkFailedRequestCount = 0
    private networkRequestDurationSum = 0
    private networkRequestDurationSumOfSquares = 0
    private networkRequestDurationCount = 0

    // Scroll depth
    private maxScrollY = 0

    // Click target diversity
    private clickTargetIds: Set<number> = new Set()

    // Text selection
    private textSelectionCount = 0

    constructor(
        public readonly sessionId: string,
        public readonly teamId: number,
        public readonly batchId: string
    ) {
        this._run = this.shouldRun(sessionId)
    }

    public recordMessage(message: ParsedMessageData): void {
        if (!this._run) {
            return
        }

        if (this.ended) {
            throw new Error('Cannot record message after end() has been called')
        }

        if (!this._distinctId) {
            this._distinctId = message.distinct_id
        }

        if (!this.startDateTime || message.eventsRange.start < this.startDateTime) {
            this.startDateTime = message.eventsRange.start
        }
        if (!this.endDateTime || message.eventsRange.end > this.endDateTime) {
            this.endDateTime = message.eventsRange.end
        }

        for (const [_windowId, events] of Object.entries(message.eventsByWindowId)) {
            for (const event of events) {
                this.aggregateFeatures(event)
                this.eventCount++
            }
        }
    }

    /** Ad-hoc rollout md5 gate */
    private shouldRun(sessionId: string): boolean {
        const rolloutPercentage = defaultConfig.SESSION_RECORDING_FEATURES_ROLLOUT_PERCENTAGE
        if (rolloutPercentage >= 100) {
            return true
        }
        if (rolloutPercentage <= 0) {
            return false
        }
        const hash = crypto.createHash('md5').update(sessionId).digest('hex')
        const hashValue = parseInt(hash.substring(0, 8), 16)
        const percentage = (hashValue % 10000) / 100
        return percentage < rolloutPercentage
    }

    private aggregateFeatures(event: SnapshotEvent): void {
        const e = event as RRWebEventData
        this.trackMousePosition(e)
        this.trackScroll(e)
        this.trackClicks(event, e)
        this.trackKeypress(event, e.timestamp)
        this.trackInterActionTiming(event, e.timestamp)
        this.trackNavigation(event, e.timestamp)
        this.trackConsoleErrors(e)
        this.trackNetworkRequests(e)
        this.trackTextSelection(e)

        if (isMouseActivity(event)) {
            this.mouseActivityCount++
        }
    }

    private trackMousePosition(e: RRWebEventData): void {
        if (e.type !== RRWebEventType.IncrementalSnapshot || e.data?.source !== RRWebEventSource.MouseMove) {
            return
        }

        const positions = e.data.positions
        if (!positions) {
            return
        }

        for (const pos of positions) {
            const posTimestamp = e.timestamp + (pos.timeOffset || 0)

            this.mousePositionCount++
            this.mouseSumX += pos.x
            this.mouseSumXSquared += pos.x * pos.x
            this.mouseSumY += pos.y
            this.mouseSumYSquared += pos.y * pos.y

            if (this.lastMouseX !== null && this.lastMouseY !== null) {
                const dx = pos.x - this.lastMouseX
                const dy = pos.y - this.lastMouseY
                const distance = Math.sqrt(dx * dx + dy * dy)
                this.mouseDistanceTraveled += distance

                if (this.lastMouseDx !== null && this.lastMouseDy !== null) {
                    if (dx * this.lastMouseDx + dy * this.lastMouseDy < 0) {
                        this.mouseDirectionChangeCount++
                    }
                }
                this.lastMouseDx = dx
                this.lastMouseDy = dy

                if (this.lastMouseTimestamp !== null) {
                    const dt = posTimestamp - this.lastMouseTimestamp
                    if (dt > 0) {
                        const velocity = distance / dt
                        this.mouseVelocitySum += velocity
                        this.mouseVelocitySumOfSquares += velocity * velocity
                        this.mouseVelocityCount++
                    }
                }
            }

            this.lastMouseX = pos.x
            this.lastMouseY = pos.y
            this.lastMouseTimestamp = posTimestamp
        }
    }

    private trackScroll(e: RRWebEventData): void {
        if (e.type !== RRWebEventType.IncrementalSnapshot || e.data?.source !== RRWebEventSource.Scroll) {
            return
        }

        this.scrollEventCount++
        const scrollY = e.data.y
        const scrollId = e.data.id
        if (scrollY === undefined) {
            return
        }

        if (scrollY > this.maxScrollY) {
            this.maxScrollY = scrollY
        }

        // Reset tracking when the scroll target element changes
        if (scrollId !== this.lastScrollId) {
            this.lastScrollY = null
            this.lastScrollDirection = null
            this.lastScrollId = scrollId ?? null
        }

        if (this.lastScrollY === null) {
            this.lastScrollY = scrollY
            this.lastScrollTimestamp = e.timestamp
            return
        }

        const deltaY = scrollY - this.lastScrollY
        this.totalScrollMagnitude += Math.abs(deltaY)

        if (deltaY !== 0) {
            const direction: 'up' | 'down' = deltaY < 0 ? 'up' : 'down'
            if (this.lastScrollDirection !== null && direction !== this.lastScrollDirection) {
                this.scrollDirectionReversalCount++
                if (this.lastScrollTimestamp !== null && e.timestamp - this.lastScrollTimestamp < 500) {
                    this.rapidScrollReversalCount++
                }
            }
            this.lastScrollDirection = direction
        }

        this.lastScrollY = scrollY
        this.lastScrollTimestamp = e.timestamp
    }

    private trackClicks(event: SnapshotEvent, e: RRWebEventData): void {
        if (!isClick(event)) {
            return
        }

        this.clickCount++
        this.lastUserActionTimestamp = e.timestamp

        const clickTargetId = e.data?.id
        if (clickTargetId !== undefined && this.clickTargetIds.size < MAX_UNIQUE_VALUES) {
            this.clickTargetIds.add(clickTargetId)
        }

        const clickX = e.data?.x
        const clickY = e.data?.y

        const canCompare =
            this.lastClickTimestamp !== null &&
            clickX !== undefined &&
            clickY !== undefined &&
            this.lastClickX !== null &&
            this.lastClickY !== null

        if (!canCompare) {
            this.consecutiveClickCount = 1
            this.urlChangedSinceLastClick = false
            this.lastClickTimestamp = e.timestamp
            this.lastClickX = clickX ?? null
            this.lastClickY = clickY ?? null
            return
        }

        const timeDelta = e.timestamp - this.lastClickTimestamp!
        const dx = clickX! - this.lastClickX!
        const dy = clickY! - this.lastClickY!
        const distance = Math.sqrt(dx * dx + dy * dy)

        if (timeDelta < 1000 && distance < 30) {
            this.consecutiveClickCount++
            if (this.consecutiveClickCount >= 3) {
                this.rageClickCount++
            }
        } else {
            if (this.consecutiveClickCount === 1 && !this.urlChangedSinceLastClick) {
                this.deadClickCount++
            }
            this.consecutiveClickCount = 1
            this.urlChangedSinceLastClick = false
        }

        this.lastClickTimestamp = e.timestamp
        this.lastClickX = clickX ?? null
        this.lastClickY = clickY ?? null
    }

    private trackKeypress(event: SnapshotEvent, timestamp: number): void {
        if (!isKeypress(event)) {
            return
        }
        this.keypressCount++
        this.lastUserActionTimestamp = timestamp
    }

    private trackInterActionTiming(event: SnapshotEvent, timestamp: number): void {
        if (!isClick(event) && !isKeypress(event)) {
            return
        }

        if (this.lastActionTimestamp !== null) {
            const gap = timestamp - this.lastActionTimestamp
            if (gap > 0) {
                this.interActionGapCount++
                this.interActionGapSumMs += gap
                this.interActionGapSumOfSquaresMs += gap * gap
                if (gap > this.maxIdleGapMs) {
                    this.maxIdleGapMs = gap
                }
            }
        }
        this.lastActionTimestamp = timestamp
    }

    private trackNavigation(event: SnapshotEvent, timestamp: number): void {
        const eventUrl = hrefFrom(event)
        if (!eventUrl) {
            return
        }

        this.pageVisitCount++
        if (this.visitedUrls.size < MAX_UNIQUE_VALUES) {
            this.visitedUrls.add(md5Hex(eventUrl))
        }
        this.urlChangedSinceLastClick = true

        if (
            this.lastNavigationUrl !== null &&
            this.lastNavigationTimestamp !== null &&
            timestamp - this.lastNavigationTimestamp < 2000 &&
            eventUrl !== this.lastNavigationUrl
        ) {
            this.quickBackCount++
        }
        this.lastNavigationUrl = eventUrl
        this.lastNavigationTimestamp = timestamp
    }

    private trackConsoleErrors(e: RRWebEventData): void {
        if (e.type !== RRWebEventType.Plugin) {
            return
        }
        if (e.data?.plugin !== 'rrweb/console@1' || e.data?.payload?.level !== 'error') {
            return
        }

        this.consoleErrorCount++
        if (this.lastUserActionTimestamp === null) {
            return
        }

        const timeSinceAction = e.timestamp - this.lastUserActionTimestamp
        if (timeSinceAction >= 0 && timeSinceAction < 5000) {
            this.consoleErrorAfterClickCount++
        }
    }

    private trackNetworkRequests(e: RRWebEventData): void {
        if (e.type !== RRWebEventType.Plugin) {
            return
        }

        const plugin = e.data?.plugin
        if (plugin === RRWEB_NETWORK_PLUGIN) {
            const requests = e.data?.payload?.requests
            if (!Array.isArray(requests)) {
                return
            }
            for (const req of requests) {
                this.processNetworkRequest(req.duration, req.status ?? req.responseStatus)
            }
        } else if (plugin === POSTHOG_NETWORK_PLUGIN) {
            const payload = e.data?.payload
            if (!payload) {
                return
            }
            this.processNetworkRequest(
                payload[POSTHOG_NETWORK_DURATION_KEY] as number | undefined,
                payload[POSTHOG_NETWORK_STATUS_KEY] as number | undefined
            )
        }
    }

    private processNetworkRequest(duration: unknown, status: unknown): void {
        this.networkRequestCount++

        if (typeof status === 'number' && status >= 400) {
            this.networkFailedRequestCount++
        }

        if (typeof duration === 'number' && duration > 0) {
            this.networkRequestDurationSum += duration
            this.networkRequestDurationSumOfSquares += duration * duration
            this.networkRequestDurationCount++
        }
    }

    private trackTextSelection(e: RRWebEventData): void {
        if (e.type !== RRWebEventType.IncrementalSnapshot || e.data?.source !== RRWebEventSource.Selection) {
            return
        }
        this.textSelectionCount++
    }

    public get distinctId(): string {
        if (!this._distinctId) {
            throw new Error('No distinct_id set. No messages recorded yet.')
        }
        return this._distinctId
    }

    public end(): FeatureEndResult | null {
        if (!this._run) {
            return null
        }

        if (this.ended) {
            throw new Error('end() has already been called')
        }
        this.ended = true

        return {
            startDateTime: this.startDateTime ?? DateTime.fromMillis(0),
            endDateTime: this.endDateTime ?? DateTime.fromMillis(0),
            eventCount: this.eventCount,

            mousePositionCount: this.mousePositionCount,
            mouseSumX: this.mouseSumX,
            mouseSumXSquared: this.mouseSumXSquared,
            mouseSumY: this.mouseSumY,
            mouseSumYSquared: this.mouseSumYSquared,

            mouseDistanceTraveled: this.mouseDistanceTraveled,
            mouseDirectionChangeCount: this.mouseDirectionChangeCount,

            mouseVelocitySum: this.mouseVelocitySum,
            mouseVelocitySumOfSquares: this.mouseVelocitySumOfSquares,
            mouseVelocityCount: this.mouseVelocityCount,

            scrollEventCount: this.scrollEventCount,
            totalScrollMagnitude: this.totalScrollMagnitude,
            scrollDirectionReversalCount: this.scrollDirectionReversalCount,
            rapidScrollReversalCount: this.rapidScrollReversalCount,

            clickCount: this.clickCount,
            keypressCount: this.keypressCount,
            mouseActivityCount: this.mouseActivityCount,
            rageClickCount: this.rageClickCount,
            deadClickCount: this.deadClickCount,

            interActionGapCount: this.interActionGapCount,
            interActionGapSumMs: this.interActionGapSumMs,
            interActionGapSumOfSquaresMs: this.interActionGapSumOfSquaresMs,
            maxIdleGapMs: this.maxIdleGapMs,

            quickBackCount: this.quickBackCount,
            pageVisitCount: this.pageVisitCount,
            visitedUrls: Array.from(this.visitedUrls),

            consoleErrorCount: this.consoleErrorCount,
            consoleErrorAfterClickCount: this.consoleErrorAfterClickCount,

            networkRequestCount: this.networkRequestCount,
            networkFailedRequestCount: this.networkFailedRequestCount,
            networkRequestDurationSum: this.networkRequestDurationSum,
            networkRequestDurationSumOfSquares: this.networkRequestDurationSumOfSquares,
            networkRequestDurationCount: this.networkRequestDurationCount,

            maxScrollY: this.maxScrollY,

            clickTargetIds: Array.from(this.clickTargetIds),

            textSelectionCount: this.textSelectionCount,
        }
    }
}
