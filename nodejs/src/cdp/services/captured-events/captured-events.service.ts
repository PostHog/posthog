import { Counter, Gauge } from 'prom-client'

import {
    InternalCaptureEvent,
    InternalCaptureService,
    isTransientNetworkError,
} from '~/common/services/internal-capture'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { CyclotronJobInvocationResult } from '../../types'

const capturedEventsPending = new Gauge({
    name: 'cdp_captured_events_pending',
    help: 'Number of internal capture events queued and waiting to be flushed. High values indicate accumulation and potential memory leak.',
})

const capturedEventsFlushErrors = new Counter({
    name: 'cdp_captured_events_flush_errors',
    help: 'Internal capture failures during flush, split by whether they were reported to error tracking.',
    labelNames: ['transient'],
})

/**
 * Collects and flushes PostHog capture events emitted by hog function
 * invocations via `posthog.capture()`. Lifecycle mirrors the sibling
 * monitoring/warehouse services: `queueInvocationResults` extracts events from
 * the result batch, `flush()` drains them through the shared internal-capture
 * service.
 */
export class CapturedEventsService {
    private queuedEvents: InternalCaptureEvent[] = []

    constructor(
        private internalCaptureService: InternalCaptureService,
        private teamManager: TeamManager
    ) {}

    /** Append already-resolved events onto the flush buffer. */
    queue(events: InternalCaptureEvent[]): void {
        if (events.length === 0) {
            return
        }
        for (const event of events) {
            this.queuedEvents.push(event)
        }
        capturedEventsPending.set(this.queuedEvents.length)
    }

    /**
     * Resolve the team for a single event (to obtain the API token) and queue it.
     * Used by code paths outside the invocation-result lifecycle, e.g. SES webhooks.
     */
    async queueEvent(event: { team_id: number } & Omit<InternalCaptureEvent, 'team_token'>): Promise<void> {
        const team = await this.teamManager.getTeam(event.team_id)
        if (!team) {
            return
        }
        this.queuedEvents.push({
            team_token: team.api_token,
            event: event.event,
            distinct_id: event.distinct_id,
            timestamp: event.timestamp,
            properties: event.properties,
        })
        capturedEventsPending.set(this.queuedEvents.length)
    }

    /**
     * Extract `capturedPostHogEvents` from each result, resolve the team
     * (to obtain the API token used by capture), and queue.
     */
    async queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        await Promise.all(
            results.map(async (result) => {
                const capturedEvents = result.capturedPostHogEvents
                if (!capturedEvents || capturedEvents.length === 0) {
                    return
                }
                for (const event of capturedEvents) {
                    const team = await this.teamManager.getTeam(event.team_id)
                    if (!team) {
                        continue
                    }
                    this.queuedEvents.push({
                        team_token: team.api_token,
                        event: event.event,
                        distinct_id: event.distinct_id,
                        timestamp: event.timestamp,
                        properties: event.properties,
                    })
                }
                capturedEventsPending.set(this.queuedEvents.length)
            })
        )
    }

    async flush(): Promise<void> {
        const events = this.queuedEvents
        this.queuedEvents = []
        capturedEventsPending.set(0)

        if (events.length === 0) {
            return
        }

        await Promise.all(
            events.map((event) =>
                this.internalCaptureService.capture(event).catch((error) => {
                    // Capture is fire-and-forget, so a transient in-cluster DNS/network
                    // blip (that already survived the retries in InternalCaptureService)
                    // breaks nothing downstream. Don't page error tracking with it, or it
                    // buries genuine failures. Real, non-transient failures still report.
                    if (isTransientNetworkError(error)) {
                        capturedEventsFlushErrors.inc({ transient: 'true' })
                        logger.warn('Transient network error capturing internal event, not reporting', { error })
                        return
                    }
                    capturedEventsFlushErrors.inc({ transient: 'false' })
                    logger.error('Error capturing internal event', { error })
                    captureException(error)
                })
            )
        )
    }
}
