import { Properties } from '@posthog/plugin-scaffold'
import crypto from 'crypto'
import { DateTime } from 'luxon'
import { Hub, PluginConfig, RawEventMessage } from 'types'

import { status } from '../../../utils/status'
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

async function queueEvent(hub: Hub, pluginConfig: PluginConfig, data: InternalData): Promise<void> {
    const partitionKeyHash = crypto.createHash('sha256')
    partitionKeyHash.update(`${data.team_id}:${data.distinct_id}`)
    const partitionKey = partitionKeyHash.digest('hex')

    const message = JSON.stringify({
        distinct_id: data.distinct_id,
        ip: '',
        site_url: '',
        data: JSON.stringify(data),
        team_id: pluginConfig.team_id,
        now: data.timestamp,
        sent_at: data.timestamp,
        uuid: data.uuid,
    } as RawEventMessage)

    // We currently don't drop or truncate oversized events, although Kafka will reject the messages anyway.
    // Log events over 1MB so that can dig into what event type triggers KafkaJSProtocolError when we see them.
    const messageSize = Buffer.from(message).length
    if (messageSize > 1_000_000) {
        status.warn('⚠️', 'App captured an event over 1MB, writing it to Kafka will probably fail', {
            team: pluginConfig.team_id,
            plugin: pluginConfig.plugin?.name,
            event: data.event,
            estimatedSize: messageSize,
        })
    }

    await hub.kafkaProducer.queueMessage({
        topic: hub.KAFKA_CONSUMPTION_TOPIC!,
        messages: [
            {
                key: partitionKey,
                value: message,
            },
        ],
    })
}

export function createPosthog(hub: Hub, pluginConfig: PluginConfig): DummyPostHog {
    const distinctId = pluginConfig.plugin?.name || `plugin-id-${pluginConfig.plugin_id}`

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
                team_id: pluginConfig.team_id,
                uuid: new UUIDT().toString(),
            }
            await queueEvent(hub, pluginConfig, data)
            hub.statsd?.increment('vm_posthog_extension_capture_called')
        },
        api: createApi(hub, pluginConfig),
    }
}
