import { PubSub, Topic } from '@google-cloud/pubsub'

import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { RetryError } from '@posthog/plugin-scaffold'

import { LegacyDestinationPluginMeta } from '../../types'

type PubSubMeta = LegacyDestinationPluginMeta & {
    global: {
        pubSubClient: PubSub
        pubSubTopic: Topic
    }
    config: {
        topicId: string
        googleCloudKeyJson: {
            type: string
            project_id: string
            private_key_id: string
            private_key: string
            client_email: string
            client_id: string
            auth_uri: string
            token_uri: string
            auth_provider_x509_cert_url: string
            client_x509_cert_url: string
            universe_domain: string
        }
    }
}

export const setupPlugin = async (meta: PubSubMeta): Promise<void> => {
    const { global, config, logger } = meta
    if (!config.googleCloudKeyJson) {
        throw new Error('JSON config not provided!')
    }
    if (!config.topicId) {
        throw new Error('Topic ID not provided!')
    }

    try {
        global.pubSubClient = new PubSub({
            projectId: config.googleCloudKeyJson.project_id,
            credentials: config.googleCloudKeyJson,
        })
        global.pubSubTopic = global.pubSubClient.topic(config.topicId)

        // topic exists
        await global.pubSubTopic.getMetadata()
    } catch (error) {
        // some other error? abort!
        if (!error.message.includes('NOT_FOUND')) {
            throw new Error(error)
        }
        logger.log(`Creating PubSub Topic - ${config.topicId}`)

        try {
            await global.pubSubTopic.create()
        } catch (error) {
            // a different worker already created the table
            if (!error.message.includes('ALREADY_EXISTS')) {
                throw error
            }
        }
    }
}

export async function onEvent(fullEvent: ProcessedPluginEvent, { global, config, logger }: PubSubMeta) {
    if (!global.pubSubClient) {
        throw new Error('No PubSub client initialized!')
    }
    try {
        const { event, properties, $set, $set_once, distinct_id, team_id, uuid } = fullEvent
        const ip = properties?.['$ip'] || fullEvent.ip
        const timestamp = fullEvent.timestamp || properties?.timestamp
        let ingestedProperties = properties
        let elements = []

        // only move prop to elements for the $autocapture action
        if (event === '$autocapture' && properties?.['$elements']) {
            const { $elements, ...props } = properties
            ingestedProperties = props
            elements = $elements
        }

        const message = {
            event,
            distinct_id,
            team_id,
            ip,
            timestamp,
            uuid: uuid!,
            properties: ingestedProperties || {},
            elements: elements || [],
            people_set: $set || {},
            people_set_once: $set_once || {},
        }
        const dataBuf = Buffer.from(JSON.stringify(message))

        await global.pubSubTopic.publish(dataBuf).then((messageId) => {
            return messageId
        })
    } catch (error) {
        logger.error(`Error publishing ${fullEvent.uuid} to ${config.topicId}: `, error)
        throw new RetryError(`Error publishing to Pub/Sub! ${JSON.stringify(error.errors)}`)
    }
}
