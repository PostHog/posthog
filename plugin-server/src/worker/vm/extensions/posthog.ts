import { Properties } from '@posthog/plugin-scaffold'
import crypto from 'crypto'
import { DateTime } from 'luxon'
import { Hub, RawEventMessage } from 'types'
import { v4 } from 'uuid'

import { UUIDT } from '../../../utils/utils'
import { ApiExtension, createApi } from './api'

const { version } = require('../../../../package.json')

interface InternalData {
    distinct_id: string
    event: string
    timestamp: string
    properties: Properties
    team_id: number
    uuid: string
}

export interface DummyPostHog {
    capture(event: string, properties?: Record<string, any>): Promise<void>
    api: ApiExtension
}

async function queueEvent(hub: Hub, teamId: number, data: InternalData): Promise<void> {
    const partitionKeyHash = crypto.createHash('sha256')
    partitionKeyHash.update(`${data.team_id}:${data.distinct_id}`)
    const partitionKey = partitionKeyHash.digest('hex')

    await hub.kafkaProducer.queueMessage({
        topic: hub.KAFKA_CONSUMPTION_TOPIC!,
        messages: [
            {
                key: partitionKey,
                value: JSON.stringify({
                    distinct_id: data.distinct_id,
                    ip: '',
                    site_url: '',
                    data: JSON.stringify(data),
                    team_id: teamId,
                    now: data.timestamp,
                    sent_at: data.timestamp,
                    uuid: data.uuid,
                } as RawEventMessage),
            },
        ],
    })
}

export function createPosthog(hub: Hub, teamId: number, distinctId = v4()): DummyPostHog {
    return {
        capture: async (event, properties = {}) => {
            const { timestamp = DateTime.utc().toISO(), distinct_id = distinctId, ...otherProperties } = properties
            const data: InternalData = {
                distinct_id,
                event,
                timestamp,
                properties: {
                    $lib: 'posthog-plugin-server',
                    $lib_version: version,
                    distinct_id,
                    ...otherProperties,
                },
                team_id: teamId,
                uuid: new UUIDT().toString(),
            }
            await queueEvent(hub, teamId, data)
            hub.statsd?.increment('vm_posthog_extension_capture_called')
        },
        api: createApi(hub, teamId),
    }
}
