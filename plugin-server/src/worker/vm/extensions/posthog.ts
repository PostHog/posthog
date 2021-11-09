import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Hub, PluginConfig, RawEventMessage } from 'types'

import { Client } from '../../../utils/celery/client'
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

export function createPosthog(server: Hub, pluginConfig: PluginConfig): DummyPostHog {
    const distinctId = pluginConfig.plugin?.name || `plugin-id-${pluginConfig.plugin_id}`

    let sendEvent: (data: InternalData) => Promise<void>

    if (server.KAFKA_ENABLED) {
        // Sending event to our Kafka>ClickHouse pipeline
        sendEvent = async (data) => {
            if (!server.kafkaProducer) {
                throw new Error('kafkaProducer not configured!')
            }
            // ignore the promise, run in the background just like with celery
            await server.kafkaProducer.queueMessage({
                topic: server.KAFKA_CONSUMPTION_TOPIC!,
                messages: [
                    {
                        key: data.uuid,
                        value: JSON.stringify({
                            distinct_id: data.distinct_id,
                            ip: '',
                            site_url: '',
                            data: JSON.stringify(data),
                            team_id: pluginConfig.team_id,
                            now: data.timestamp,
                            sent_at: data.timestamp,
                            uuid: data.uuid,
                        } as RawEventMessage),
                    },
                ],
            })
        }
    } else {
        // Sending event to our Redis>Postgres pipeline
        const client = new Client(server.db, server.PLUGINS_CELERY_QUEUE)
        sendEvent = async (data) => {
            await client.sendTaskAsync(
                'posthog.tasks.process_event.process_event_with_plugins',
                [data.distinct_id, null, null, data, pluginConfig.team_id, data.timestamp, data.timestamp],
                {}
            )
        }
    }

    return {
        async capture(event, properties = {}) {
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
            await sendEvent(data)
        },
        api: createApi(server, pluginConfig),
    }
}
