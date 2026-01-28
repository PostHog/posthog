import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { PluginsServerConfig } from '~/types'
import { logger } from '~/utils/logger'
import { FetchResponse, internalFetch } from '~/utils/request'

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

export class InternalCaptureService {
    constructor(private config: Pick<PluginsServerConfig, 'CAPTURE_INTERNAL_URL'>) {}

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
