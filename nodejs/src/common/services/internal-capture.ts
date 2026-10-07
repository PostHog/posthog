import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { CommonConfig } from '~/common/config'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'
import { RetrySchedule, retryIfRetriable } from '~/common/utils/retries'

const internalCaptureCounter = new Counter({
    name: 'internal_capture_events',
    help: 'Number of internal capture events',
    labelNames: ['status'],
})

const internalCaptureAttemptFailureCounter = new Counter({
    name: 'internal_capture_request_attempt_failures',
    help: 'Internal capture requests that failed, by reason. A request can fail several attempts before it succeeds.',
    labelNames: ['reason'],
})

// Capture sits next to the worker in the cluster, so a failure is short lived. Two retries cover a rolling restart or
// a dropped connection without holding a flush open: an attempt takes at most EXTERNAL_REQUEST_TIMEOUT_MS.
const CAPTURE_RETRY_SCHEDULE: RetrySchedule = {
    tries: 3,
    sleepMs: 50,
    backoffFactor: 4,
    maxSleepMs: 1000,
    softDeadlineMs: 5000,
}

/** Capture refuses a wire body above 20 MB. Internal events are small, so this chunk stays far below the ceiling. */
export const MAX_EVENTS_PER_CAPTURE_REQUEST = 500

export type InternalCaptureEvent = {
    team_token: string
    event: string
    distinct_id: string
    properties?: Record<string, any>
    timestamp?: string
}

type CaptureBatchFormat = {
    api_key: string
    sent_at: string
    batch: {
        timestamp: string
        distinct_id: string
        event: string
        properties: Record<string, any>
    }[]
}

/** Capture answered. A 4xx is the same answer every time, so only the rest is worth another attempt. */
class CaptureStatusError extends Error {
    readonly isRetriable: boolean
    constructor(readonly status: number) {
        super(`Internal capture answered with status ${status}`)
        this.name = 'CaptureStatusError'
        this.isRetriable = status === 429 || status >= 500
    }
}

/** Undici reports a transport failure through `code`, for example a connect timeout. */
function failureReason(error: unknown): string {
    if (error instanceof CaptureStatusError) {
        return `status_${error.status}`
    }
    const code = (error as { code?: unknown })?.code
    return typeof code === 'string' ? code : 'error'
}

export class InternalCaptureService {
    constructor(private config: Pick<CommonConfig, 'CAPTURE_INTERNAL_URL'>) {}

    private prepareBatch(teamToken: string, events: InternalCaptureEvent[]): CaptureBatchFormat {
        const now = DateTime.utc().toISO()
        return {
            api_key: teamToken,
            sent_at: now,
            batch: events.map((event) => ({
                timestamp: event.timestamp ?? now,
                distinct_id: event.distinct_id,
                event: event.event,
                properties: { ...(event.properties ?? {}), capture_internal: true },
            })),
        }
    }

    /**
     * One POST. The body is always drained: undici holds the socket out of the pool until the body is read, so a
     * caller that ignores it makes every capture open a new connection.
     */
    private async send(body: string): Promise<number> {
        try {
            const response = await internalFetch(this.config.CAPTURE_INTERNAL_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body,
            })
            await response.dump()

            if (response.status >= 400) {
                throw new CaptureStatusError(response.status)
            }
            return response.status
        } catch (error) {
            internalCaptureAttemptFailureCounter.inc({ reason: failureReason(error) })
            throw error
        }
    }

    /**
     * Sends one team's events in a single request. Capture reads a batch body on the same path a single event uses,
     * so a flush costs one request per team rather than one per event.
     *
     * Resolves when capture accepted the batch. Throws when every attempt failed, so the caller can count the loss.
     */
    async captureBatch(teamToken: string, events: InternalCaptureEvent[]): Promise<void> {
        if (events.length === 0) {
            return
        }
        logger.debug('Capturing internal events', { count: events.length, url: this.config.CAPTURE_INTERNAL_URL })
        const body = JSON.stringify(this.prepareBatch(teamToken, events))

        let status: number
        try {
            status = await retryIfRetriable(() => this.send(body), CAPTURE_RETRY_SCHEDULE)
        } catch (error) {
            // A rejection keeps its status, so the counter still separates a bad token from capture being unreachable.
            const label = error instanceof CaptureStatusError ? error.status.toString() : 'error'
            internalCaptureCounter.inc({ status: label }, events.length)
            throw error
        }

        internalCaptureCounter.inc({ status: status.toString() }, events.length)
    }

    async capture(event: InternalCaptureEvent): Promise<void> {
        await this.captureBatch(event.team_token, [event])
    }
}
