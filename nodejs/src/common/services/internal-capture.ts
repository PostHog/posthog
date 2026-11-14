import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { CommonConfig } from '~/common/config'
import { logger } from '~/common/utils/logger'
import { FetchResponse, internalFetch } from '~/common/utils/request'
import { UUIDT, delay } from '~/common/utils/utils'

const internalCaptureCounter = new Counter({
    name: 'internal_capture_events',
    help: 'Number of internal capture events',
    labelNames: ['status'],
})

export type InternalCaptureEvent = {
    team_token: string
    event: string
    distinct_id: string
    properties?: Record<string, any>
    timestamp?: string
}

// One retry after a jittered pause covers a pooled socket that a capture rollout closed mid-request.
const MAX_ATTEMPTS = 2
const RETRY_DELAY_MS = 250

type CapturePayloadFormat = {
    uuid: string
    api_key: string
    timestamp: string
    distinct_id: string
    sent_at: string
    event: string
    properties: Record<string, any>
}

/** An internal event carries the server's IP, not the user's. GeoIP would turn it into a wrong or
 * placeholder location and write that over the person's real location. */
export function disableGeoipWithoutClientIp(properties: Record<string, any>): Record<string, any> {
    return properties.$ip ? properties : { $geoip_disable: true, ...properties }
}

export class InternalCaptureService {
    constructor(private config: Pick<CommonConfig, 'CAPTURE_INTERNAL_URL'>) {}

    private prepareEvent(event: InternalCaptureEvent): CapturePayloadFormat {
        const properties = { ...disableGeoipWithoutClientIp(event.properties ?? {}), capture_internal: true }
        const now = DateTime.utc().toISO()
        return {
            // Reused on retry so the events table collapses a resend that capture already ingested.
            uuid: new UUIDT().toString(),
            api_key: event.team_token,
            timestamp: event.timestamp ?? now,
            distinct_id: event.distinct_id,
            sent_at: now,
            event: event.event,
            properties,
        }
    }

    async capture(event: InternalCaptureEvent): Promise<FetchResponse> {
        logger.debug('Capturing internal event', { event, url: this.config.CAPTURE_INTERNAL_URL })
        const body = JSON.stringify(this.prepareEvent(event))
        for (let attempt = 1; ; attempt++) {
            try {
                const response = await internalFetch(this.config.CAPTURE_INTERNAL_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body,
                })
                if (response.status < 500 || attempt >= MAX_ATTEMPTS) {
                    logger.debug('Internal capture event captured', { status: response.status })
                    internalCaptureCounter.inc({ status: response.status.toString() })
                    return response
                }
                await response.dump()
            } catch (e) {
                if (attempt >= MAX_ATTEMPTS) {
                    internalCaptureCounter.inc({ status: 'error' })
                    logger.error('Error capturing internal event', { error: e })
                    throw e
                }
            }
            internalCaptureCounter.inc({ status: 'retry' })
            await delay(RETRY_DELAY_MS / 2 + Math.random() * (RETRY_DELAY_MS / 2))
        }
    }
}
