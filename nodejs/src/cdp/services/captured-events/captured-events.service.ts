import { Gauge } from 'prom-client'

import { InternalCaptureEvent, InternalCaptureService } from '~/common/services/internal-capture'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { Team } from '../../../types'
import { CyclotronJobInvocationResult } from '../../types'

export const CAPTURE_BATCH_SIZE = 100
// Capture refuses request bodies over 20 MiB, and one event can carry about 1 MiB of properties.
export const CAPTURE_BATCH_MAX_BYTES = 2 * 1024 * 1024
export const CAPTURE_BATCH_CONCURRENCY = 5

export function buildCaptureBatches(events: InternalCaptureEvent[]): InternalCaptureEvent[][] {
    // Capture reads one token per request body, so batches never mix team tokens.
    const byToken = new Map<string, InternalCaptureEvent[]>()
    for (const event of events) {
        const group = byToken.get(event.team_token)
        if (group) {
            group.push(event)
        } else {
            byToken.set(event.team_token, [event])
        }
    }
    const batches: InternalCaptureEvent[][] = []
    for (const group of byToken.values()) {
        let batch: InternalCaptureEvent[] = []
        let batchBytes = 0
        for (const event of group) {
            const eventBytes = JSON.stringify(event).length
            if (
                batch.length > 0 &&
                (batch.length >= CAPTURE_BATCH_SIZE || batchBytes + eventBytes > CAPTURE_BATCH_MAX_BYTES)
            ) {
                batches.push(batch)
                batch = []
                batchBytes = 0
            }
            batch.push(event)
            batchBytes += eventBytes
        }
        if (batch.length > 0) {
            batches.push(batch)
        }
    }
    return batches
}

const capturedEventsPending = new Gauge({
    name: 'cdp_captured_events_pending',
    help: 'Number of internal capture events queued and waiting to be flushed. High values indicate accumulation and potential memory leak.',
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
    private flushing: Promise<void> = Promise.resolve()

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
                const teams = new Map<number, Team | null>()
                for (const event of capturedEvents) {
                    if (!teams.has(event.team_id)) {
                        teams.set(event.team_id, await this.teamManager.getTeam(event.team_id))
                    }
                    const team = teams.get(event.team_id)
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

    // Required by ResultSink. This sink holds nothing of its own: it writes through the shared
    // Kafka outputs, which the server disconnects separately on shutdown.
    async stop(): Promise<void> {
        return Promise.resolve()
    }

    // Flushes run one after another, so the in-flight bound holds across concurrent webhook requests
    // and not only inside one flush.
    flush(): Promise<void> {
        const run = this.flushing.then(() => this.drain())
        this.flushing = run.catch(() => undefined)
        return run
    }

    private async drain(): Promise<void> {
        const events = this.queuedEvents
        this.queuedEvents = []
        capturedEventsPending.set(0)

        if (events.length === 0) {
            return
        }

        const batches = buildCaptureBatches(events)
        for (let i = 0; i < batches.length; i += CAPTURE_BATCH_CONCURRENCY) {
            await Promise.all(batches.slice(i, i + CAPTURE_BATCH_CONCURRENCY).map((batch) => this.sendBatch(batch)))
        }
    }

    private async sendBatch(batch: InternalCaptureEvent[]): Promise<void> {
        try {
            const response = await this.internalCaptureService.captureBatch(batch)
            if (batch.length === 1 || response.status < 400 || response.status >= 500) {
                return
            }
            // Capture rejects a whole body when one event in it is invalid or the body is too large.
            // Sending the events alone lets only the bad event fail.
            logger.warn('Capture rejected a batch, retrying its events one at a time', {
                status: response.status,
                count: batch.length,
            })
            await Promise.all(
                batch.map((event) =>
                    this.internalCaptureService.capture(event).catch((error) => {
                        logger.error('Error capturing internal event', { error })
                        captureException(error)
                    })
                )
            )
        } catch (error) {
            logger.error('Error capturing internal events', { error, count: batch.length })
            captureException(error)
        }
    }
}
