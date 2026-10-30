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
            api_key: event.team_token,
            timestamp: event.timestamp ?? now,
            distinct_id: event.distinct_id,
            sent_at: now,
            event: event.event,
            properties,
        }
    }

    // Capture reads one token per request body, so every event in a batch must share a team_token.
    async captureBatch(events: InternalCaptureEvent[]): Promise<FetchResponse> {
        const tokens = new Set(events.map((event) => event.team_token))
        if (tokens.size !== 1) {
            throw new Error(`captureBatch requires exactly one team_token per batch, got ${tokens.size}`)
        }
        try {
            const response = await internalFetch(this.config.CAPTURE_INTERNAL_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(events.map((event) => this.prepareEvent(event))),
            })
            internalCaptureCounter.inc({ status: response.status.toString() }, events.length)
            return response
        } catch (e) {
            internalCaptureCounter.inc({ status: 'error' }, events.length)
            logger.error('Error capturing internal event batch', { error: e, count: events.length })
            throw e
        }
    }

    async capture(event: InternalCaptureEvent): Promise<FetchResponse> {
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
            logger.error('Error capturing internal event', { error: e })
            throw e
        }
    }
}
