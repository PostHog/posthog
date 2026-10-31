import { Counter, Gauge } from 'prom-client'

import { InternalCaptureEvent, InternalCaptureService } from '~/common/services/internal-capture'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { Team } from '../../../types'
import { CyclotronJobInvocationResult } from '../../types'
import { Semaphore } from '../../utils/sempahore'

export const CAPTURE_BATCH_SIZE = 100
// Capture refuses request bodies over 20 MiB, and one event can carry about 1 MiB of properties.
export const CAPTURE_BATCH_MAX_BYTES = 2 * 1024 * 1024
export const CAPTURE_BATCH_CONCURRENCY = 5
// Events wait in memory until capture accepts them. Past this many outstanding events, queued or
// in flight, new events are dropped and counted, so a capture slowdown degrades into lost events
// instead of an out-of-memory pod.
export const CAPTURE_QUEUE_MAX_EVENTS = 10_000
// Capture answers 400 for an invalid event and 413 for an oversized body. One event can cause
// either, so such a batch is retried one event at a time. Every other status, such as 401 or 429,
// applies to the whole batch and a retry would only repeat it.
const SPLIT_RETRY_STATUSES: ReadonlySet<number> = new Set([400, 413])

const capturedEventsPending = new Gauge({
    name: 'cdp_captured_events_pending',
    help: 'Number of internal capture events queued and waiting to be flushed. High values indicate accumulation and potential memory leak.',
})

const capturedEventsDropped = new Counter({
    name: 'cdp_captured_events_dropped',
    help: 'Internal capture events that were not delivered, by reason.',
    labelNames: ['reason'],
})

export function buildCaptureBatches(events: InternalCaptureEvent[]): {
    batches: InternalCaptureEvent[][]
    unserializable: number
} {
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
    let unserializable = 0
    for (const group of byToken.values()) {
        let batch: InternalCaptureEvent[] = []
        let batchBytes = 0
        for (const event of group) {
            let eventBytes: number
            try {
                eventBytes = Buffer.byteLength(JSON.stringify(event))
            } catch {
                unserializable++
                continue
            }
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
    return { batches, unserializable }
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
    // One bound for every request to capture from this process, batches and single retries alike.
    private sends = new Semaphore(CAPTURE_BATCH_CONCURRENCY)
    private inFlight = new Set<Promise<void>>()
    private inFlightEvents = 0

    constructor(
        private internalCaptureService: InternalCaptureService,
        private teamManager: TeamManager
    ) {}

    /** Append already-resolved events onto the flush buffer. */
    queue(events: InternalCaptureEvent[]): void {
        for (const event of events) {
            this.enqueue(event)
        }
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
        this.enqueue({
            team_token: team.api_token,
            event: event.event,
            distinct_id: event.distinct_id,
            timestamp: event.timestamp,
            properties: event.properties,
        })
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
                    this.enqueue({
                        team_token: team.api_token,
                        event: event.event,
                        distinct_id: event.distinct_id,
                        timestamp: event.timestamp,
                        properties: event.properties,
                    })
                }
            })
        )
    }

    private enqueue(event: InternalCaptureEvent): void {
        if (this.queuedEvents.length + this.inFlightEvents >= CAPTURE_QUEUE_MAX_EVENTS) {
            capturedEventsDropped.inc({ reason: 'queue_full' })
            return
        }
        this.queuedEvents.push(event)
        capturedEventsPending.set(this.queuedEvents.length)
    }

    // Required by ResultSink. Drains what is queued and waits for the requests already in flight,
    // because this sink writes to capture over HTTP and nothing else holds those events.
    async stop(): Promise<void> {
        await this.flush()
        await Promise.all([...this.inFlight])
    }

    async flush(): Promise<void> {
        const events = this.queuedEvents
        this.queuedEvents = []
        capturedEventsPending.set(0)

        if (events.length === 0) {
            return
        }

        const { batches, unserializable } = buildCaptureBatches(events)
        if (unserializable > 0) {
            capturedEventsDropped.inc({ reason: 'unserializable' }, unserializable)
            logger.warn('Dropped captured events that could not be serialized', { count: unserializable })
        }
        await Promise.all(batches.map((batch) => this.track(batch, this.sendBatch(batch))))
    }

    private track(batch: InternalCaptureEvent[], promise: Promise<void>): Promise<void> {
        this.inFlightEvents += batch.length
        this.inFlight.add(promise)
        return promise.finally(() => {
            this.inFlightEvents -= batch.length
            this.inFlight.delete(promise)
        })
    }

    private async sendBatch(batch: InternalCaptureEvent[]): Promise<void> {
        try {
            const response = await this.sends.run(() => this.internalCaptureService.captureBatch(batch))
            if (response.status < 400) {
                return
            }
            if (batch.length === 1 || !SPLIT_RETRY_STATUSES.has(response.status)) {
                capturedEventsDropped.inc({ reason: `status_${response.status}` }, batch.length)
                logger.warn('Capture refused a batch of internal events', {
                    status: response.status,
                    count: batch.length,
                })
                return
            }
            logger.warn('Capture rejected a batch, retrying its events one at a time', {
                status: response.status,
                count: batch.length,
            })
            await Promise.all(batch.map((event) => this.sendSingle(event)))
        } catch (error) {
            capturedEventsDropped.inc({ reason: 'error' }, batch.length)
            logger.error('Error capturing internal events', { error, count: batch.length })
            captureException(error)
        }
    }

    private async sendSingle(event: InternalCaptureEvent): Promise<void> {
        try {
            const response = await this.sends.run(() => this.internalCaptureService.capture(event))
            if (response.status >= 400) {
                capturedEventsDropped.inc({ reason: `status_${response.status}` })
                logger.warn('Capture refused an internal event', { status: response.status, event: event.event })
            }
        } catch (error) {
            capturedEventsDropped.inc({ reason: 'error' })
            logger.error('Error capturing internal event', { error })
            captureException(error)
        }
    }
}
