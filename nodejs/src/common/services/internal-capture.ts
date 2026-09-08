import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { CommonConfig } from '~/common/config'
import { logger } from '~/common/utils/logger'
import { FetchResponse, internalFetch } from '~/common/utils/request'

const internalCaptureCounter = new Counter({
    name: 'internal_capture_events',
    help: 'Number of internal capture events',
    labelNames: ['status'],
})

// The raw rejection carries only Node timer frames, so error tracking groups every caller into one
// frameless bucket.
export class InternalCaptureError extends Error {
    constructor(
        readonly caller: string,
        readonly url: string,
        override readonly cause: unknown
    ) {
        super(`Internal capture from ${caller} to ${url} failed: ${describeCause(cause)}`)
        this.name = 'InternalCaptureError'
    }
}

function describeCause(cause: unknown): string {
    if (cause instanceof AggregateError && cause.errors.length > 0) {
        return cause.errors.map((e) => (e instanceof Error ? e.message : String(e))).join('; ')
    }
    return cause instanceof Error ? cause.message : String(cause)
}

const REMOTE_ORIGIN_CODES = new Set([
    'UND_ERR_SOCKET',
    'UND_ERR_CONNECT_TIMEOUT',
    'UND_ERR_HEADERS_TIMEOUT',
    'UND_ERR_BODY_TIMEOUT',
    'ECONNRESET',
    'ECONNREFUSED',
    'EPIPE',
    'ETIMEDOUT',
    'ENOTFOUND',
    'EAI_AGAIN',
])

// True when the write failed on the network or beyond it, which no caller can act on.
export function isRemoteOriginError(error: unknown): boolean {
    if (error instanceof InternalCaptureError) {
        return isRemoteOriginError(error.cause)
    }
    if (error instanceof AggregateError && error.errors.length > 0) {
        return error.errors.every((e) => isRemoteOriginError(e))
    }
    const candidate = error as { name?: string; code?: string } | null | undefined
    if (!candidate) {
        return false
    }
    // AbortSignal.timeout aborts with a DOMException named TimeoutError.
    return candidate.name === 'TimeoutError' || REMOTE_ORIGIN_CODES.has(candidate.code ?? '')
}

export type InternalCaptureEvent = {
    team_token: string
    event: string
    distinct_id: string
    properties?: Record<string, any>
    timestamp?: string
}

type CapturePayloadFormat = {
    api_key: string
    timestamp: string
    distinct_id: string
    sent_at: string
    event: string
    properties: Record<string, any>
}

export class InternalCaptureService {
    constructor(private config: Pick<CommonConfig, 'CAPTURE_INTERNAL_URL'>) {}

    private prepareEvent(event: InternalCaptureEvent): CapturePayloadFormat {
        const properties = { ...(event.properties ?? {}), capture_internal: true }
        const now = DateTime.utc().toISO()
        return {
            api_key: event.team_token,
            timestamp: event.timestamp ?? now,
            distinct_id: event.distinct_id,
            sent_at: now,
            event: event.event,
            properties,
        }
    }

    async capture(event: InternalCaptureEvent, caller: string): Promise<FetchResponse> {
        logger.debug('Capturing internal event', { event, url: this.config.CAPTURE_INTERNAL_URL })
        try {
            const response = await internalFetch(this.config.CAPTURE_INTERNAL_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(this.prepareEvent(event)),
            })
            logger.debug('Internal capture event captured', { status: response.status })

            internalCaptureCounter.inc({ status: response.status.toString() })
            return response
        } catch (e) {
            internalCaptureCounter.inc({ status: 'error' })
            logger.error('Error capturing internal event', { error: e, caller })
            throw new InternalCaptureError(caller, this.config.CAPTURE_INTERNAL_URL, e)
        }
    }
}
