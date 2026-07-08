import { Counter, Gauge } from 'prom-client'

import { InternalCaptureEvent, InternalCaptureService } from '~/common/services/internal-capture'
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
    help: 'Number of internal capture events that failed to flush, labelled by whether the failure was a transient in-cluster DNS resolution blip (dropped to a log line) or a real error (sent to error tracking).',
    labelNames: ['reason'],
})

// getaddrinfo failures resolving the internal capture host (capture.posthog.svc.cluster.local)
// during a CoreDNS blip are transient infra noise nobody can act on, not real exceptions.
const TRANSIENT_DNS_ERROR_CODES = new Set(['EAI_AGAIN', 'ENOTFOUND', 'EAI_NODATA', 'EAI_FAIL', 'ENODATA'])

function isTransientDnsError(error: unknown): boolean {
    // Walk the cause chain (undici wraps the underlying system error), bounded to guard against cycles.
    let current = error
    for (let depth = 0; current != null && depth < 5; depth++) {
        const code = (current as NodeJS.ErrnoException).code
        if (typeof code === 'string' && TRANSIENT_DNS_ERROR_CODES.has(code)) {
            return true
        }
        const message = (current as Error).message
        if (typeof message === 'string' && message.includes('getaddrinfo')) {
            return true
        }
        current = (current as { cause?: unknown }).cause
    }
    return false
}

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
                    if (isTransientDnsError(error)) {
                        // Transient in-cluster DNS blip — noise nobody can act on. Log + count, don't ship to error tracking.
                        capturedEventsFlushErrors.inc({ reason: 'transient_dns' })
                        logger.warn('Transient DNS failure capturing internal event', { error })
                        return
                    }
                    capturedEventsFlushErrors.inc({ reason: 'error' })
                    logger.error('Error capturing internal event', { error })
                    captureException(error)
                })
            )
        )
    }
}
