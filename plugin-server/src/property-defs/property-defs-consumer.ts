import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../kafka/config'
import { addSentryBreadcrumbsEventListeners } from '../main/ingestion-queues/kafka-metrics'
import { runInstrumentedFunction } from '../main/utils'
import {
    ClickHouseEvent,
    EventPropertyType,
    Hub,
    PluginServerService,
    PropertyDefinitionType,
    PropertyDefinitionTypeEnum,
    PropertyType,
    RawClickHouseEvent,
} from '../types'
import { parseRawClickHouseEvent } from '../utils/event'
import { status } from '../utils/status'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export const propertyDefTypesCounter = new Counter({
    name: 'property_defs_types_total',
    help: 'Count of derived property types.',
    labelNames: ['type'],
})

export type CollectedPropertyDefinitions = {
    propertyDefinitionsById: Record<string, PropertyDefinitionType>
    eventPropertiesByEventById: Record<string, EventPropertyType>
}

// These properties have special meaning, and are ignored
const SKIP_PROPERTIES: string[] = [
    '$set',
    '$set_once',
    '$unset',
    '$group_0',
    '$group_1',
    '$group_2',
    '$group_3',
    '$group_4',
    '$groups',
]

// export interface PropertyDefinitionType {
//     id: string
//     name: string
//     is_numerical: boolean
//     volume_30_day: number | null
//     query_usage_30_day: number | null
//     team_id: number
//     project_id: number | null
//     property_type?: PropertyType
//     type: PropertyDefinitionTypeEnum
//     group_type_index: number | null
// }

// export interface EventPropertyType {
//     id: string
//     event: string
//     property: string
//     team_id: number
//     project_id: number | null
// }

export const getPropertyType = (key: string, value: any): PropertyType | null => {
    // Special cases for certain property prefixes
    if (key.startsWith('utm_')) {
        // utm_ prefixed properties should always be detected as strings.
        // Sometimes the first value sent looks like a number, even though
        // subsequent values are not.
        return PropertyType.String
    }
    if (key.startsWith('$feature/')) {
        // $feature/ prefixed properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return PropertyType.String
    }

    if (key === '$feature_flag_response') {
        // $feature_flag_response properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return PropertyType.String
    }

    if (key.startsWith('$survey_response')) {
        // NB: $survey_responses are collected in an interesting way, where the first
        // response is called `$survey_response` and subsequent responses are called
        // `$survey_response_2`, `$survey_response_3`, etc. So, this check should auto-cast
        // all survey responses to strings.
        return PropertyType.String
    }

    if (typeof value === 'string') {
        const s = value.trim()
        if (s === 'true' || s === 'false' || s === 'TRUE' || s === 'FALSE') {
            return PropertyType.Boolean
        }
        // Try to parse this as an ISO 8601 date
        try {
            const date = DateTime.fromISO(s)
            if (date.isValid) {
                return PropertyType.DateTime
            }
        } catch {
            // Not a valid date, continue to string type
        }
        return PropertyType.String
    }

    if (typeof value === 'number') {
        // Check if the key contains timestamp-related keywords
        if (key.includes('timestamp') || key.includes('TIMESTAMP') || key.includes('time') || key.includes('TIME')) {
            return PropertyType.DateTime
        }
        return PropertyType.Numeric
    }

    if (typeof value === 'boolean') {
        return PropertyType.Boolean
    }

    return null
}

export class PropertyDefsConsumer {
    protected name = 'property-defs-consumer'
    protected groupId: string
    protected topic: string

    batchConsumer?: BatchConsumer
    isStopping = false
    protected heartbeat = () => {}
    protected promises: Set<Promise<any>> = new Set()

    constructor(private hub: Hub) {
        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = hub.PROPERTY_DEFS_CONSUMER_GROUP_ID
        this.topic = hub.PROPERTY_DEFS_CONSUMER_CONSUME_TOPIC
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
            batchConsumer: this.batchConsumer,
        }
    }

    public async start(): Promise<void> {
        await Promise.all([
            this.startKafkaConsumer({
                topic: this.topic,
                groupId: this.groupId,
                handleBatch: async (messages) => this.handleKafkaBatch(messages),
            }),
        ])
    }

    public async stop(): Promise<void> {
        status.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        status.info('🔁', `${this.name} - stopping batch consumer`)
        await this.batchConsumer?.stop()
        status.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy() {
        return this.batchConsumer?.isHealthy()
    }

    private scheduleWork<T>(promise: Promise<T>): Promise<T> {
        this.promises.add(promise)
        void promise.finally(() => this.promises.delete(promise))
        return promise
    }

    private runInstrumented<T>(name: string, func: () => Promise<T>): Promise<T> {
        return runInstrumentedFunction<T>({ statsKey: `propertyDefsConsumer.${name}`, func })
    }

    public async handleKafkaBatch(messages: Message[]) {
        const parsedMessages = await this.runInstrumented('parseKafkaMessages', () => this.parseKafkaBatch(messages))
        const collected = await this.runInstrumented('derivePropDefs', () =>
            Promise.resolve(this.derivePropDefs(parsedMessages))
        )

        for (const propDef of Object.values(collected.propertyDefinitionsById)) {
            propertyDefTypesCounter.inc({ type: propDef.property_type ?? 'null' })
        }

        // TODO: Get all the related property defs from the DB and compare what we would have written for all those that don't exist
        // TODO: Write prop defs to DB

        status.debug('🔁', `Waiting for promises`, { promises: this.promises.size })
        await this.runInstrumented('awaitScheduledWork', () => Promise.all(this.promises))
        status.debug('🔁', `Processed batch`)
    }

    private derivePropDefs(events: ClickHouseEvent[]): CollectedPropertyDefinitions {
        const collected: CollectedPropertyDefinitions = {
            propertyDefinitionsById: {},
            eventPropertiesByEventById: {},
        }

        for (const event of events) {
            // Detect group identify events
            if (event.event === '$groupidentify') {
                const groupType = event.properties['$group_type'] // e.g. "organization"
                const groupProperties = event.properties['$group_set'] // { name: 'value', id: 'id', foo: "bar" }

                for (const [property, value] of Object.entries(groupProperties)) {
                    const propDefId = `${event.team_id}:${groupType}:${property}`

                    if (collected.propertyDefinitionsById[propDefId]) {
                        continue
                    }

                    const propType = getPropertyType(property, value)
                    if (propType) {
                        collected.propertyDefinitionsById[propDefId] = {
                            id: propDefId,
                            name: property,
                            is_numerical: propType === PropertyType.Numeric,
                            team_id: event.team_id,
                            project_id: event.team_id, // TODO: Add project_id
                            property_type: propType,
                            type: PropertyDefinitionTypeEnum.Event,
                            group_type_index: 0, // TODO: This!
                        }
                    }
                }

                continue
            }

            // Detect person properties
            for (const [property, value] of Object.entries(event.person_properties ?? {})) {
                const propDefPersonId = `${event.team_id}:person:${property}`

                if (!collected.propertyDefinitionsById[propDefPersonId]) {
                    const propType = getPropertyType(property, value)
                    if (propType) {
                        collected.propertyDefinitionsById[propDefPersonId] = {
                            id: propDefPersonId,
                            name: property,
                            is_numerical: propType === PropertyType.Numeric,
                            team_id: event.team_id,
                            project_id: event.team_id, // TODO: Add project_id
                            property_type: propType,
                            type: PropertyDefinitionTypeEnum.Person,
                        }
                    }
                }
            }

            // Detect event properties
            for (const [property, value] of Object.entries(event.properties)) {
                if (SKIP_PROPERTIES.includes(property)) {
                    continue
                }

                const propDefEventId = `${event.team_id}:event:${property}`

                if (!collected.propertyDefinitionsById[propDefEventId]) {
                    const propType = getPropertyType(property, value)
                    if (propType) {
                        collected.propertyDefinitionsById[propDefEventId] = {
                            id: propDefEventId,
                            name: property,
                            is_numerical: propType === PropertyType.Numeric,
                            team_id: event.team_id,
                            project_id: event.team_id, // TODO: Add project_id
                            property_type: propType,
                            type: PropertyDefinitionTypeEnum.Event,
                        }
                    }
                }

                const eventDefId = `${event.team_id}:${event.event}:${property}`

                if (!collected.eventPropertiesByEventById[eventDefId]) {
                    collected.eventPropertiesByEventById[eventDefId] = {
                        id: eventDefId,
                        event: event.event,
                        property,
                        team_id: event.team_id,
                        project_id: event.team_id, // TODO: Add project_id
                    }
                }
            }
        }

        return collected
    }

    private parseKafkaBatch(messages: Message[]): Promise<ClickHouseEvent[]> {
        const events: ClickHouseEvent[] = []

        messages.forEach((message) => {
            try {
                const clickHouseEvent = parseRawClickHouseEvent(
                    JSON.parse(message.value!.toString()) as RawClickHouseEvent
                )

                events.push(clickHouseEvent)
            } catch (e) {
                status.error('Error parsing message', e)
            }
        })

        return Promise.resolve(events)
    }

    private async startKafkaConsumer(options: {
        topic: string
        groupId: string
        handleBatch: (messages: Message[]) => Promise<void>
    }): Promise<void> {
        this.batchConsumer = await startBatchConsumer({
            ...options,
            connectionConfig: createRdConnectionConfigFromEnvVars(this.hub, 'consumer'),
            autoCommit: true,
            sessionTimeout: this.hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
            maxPollIntervalMs: this.hub.KAFKA_CONSUMPTION_MAX_POLL_INTERVAL_MS,
            consumerMaxBytes: this.hub.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.hub.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            consumerMaxWaitMs: this.hub.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: this.hub.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            fetchBatchSize: this.hub.INGESTION_BATCH_SIZE,
            batchingTimeoutMs: this.hub.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicCreationTimeoutMs: this.hub.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            topicMetadataRefreshInterval: this.hub.KAFKA_TOPIC_METADATA_REFRESH_INTERVAL_MS,
            eachBatch: async (messages, { heartbeat }) => {
                status.info('🔁', `${this.name} - handling batch`, {
                    size: messages.length,
                })

                this.heartbeat = heartbeat

                // histogramKafkaBatchSize.observe(messages.length)
                // histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                return await runInstrumentedFunction({
                    statsKey: `propertyDefsConsumer.handleEachBatch`,
                    sendTimeoutGuardToSentry: false,
                    func: async () => {
                        await options.handleBatch(messages)
                    },
                })
            },
            callEachBatchWhenEmpty: false,
        })

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            if (!this.isStopping) {
                return
            }
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', `${this.name} batch consumer disconnected, cleaning up`, { err })
            await this.stop()
        })
    }
}
