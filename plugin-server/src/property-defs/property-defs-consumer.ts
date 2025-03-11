import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../kafka/config'
import { addSentryBreadcrumbsEventListeners } from '../main/ingestion-queues/kafka-metrics'
import { runInstrumentedFunction } from '../main/utils'
import {
    ClickHouseEvent,
    EventDefinitionType,
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
import { PropertyDefsDB } from './services/property-defs-db'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// TODO(eli): wire up LOTS more metrics ASAP!

const propertyDefTypesCounter = new Counter({
    name: 'property_defs_types_total',
    help: 'Count of derived property types.',
    labelNames: ['type'],
})

const eventDefTypesCounter = new Counter({
    name: 'event_defs_types_total',
    help: 'Count of new event definitions.',
})

const eventPropTypesCounter = new Counter({
    name: 'event_props_types_total',
    help: 'Count of derived event properties.',
})

const propDefDroppedCounter = new Counter({
    name: 'prop_defs_dropped_total',
    help: 'Count of property definitions dropped.',
    labelNames: ['type', 'reason'],
})

export type CollectedPropertyDefinitions = {
    teamIdsInBatch: Set<number>
    teamIdsWithGroupUpdatesInBatch: Set<number>
    eventDefinitionsById: Record<string, EventDefinitionType>
    propertyDefinitionsById: Record<string, PropertyDefinitionType>
    eventPropertiesById: Record<string, EventPropertyType>
}

// lifted from here:
// https://github.com/PostHog/posthog/blob/021aaab04b4acd96cf8121c033ac3b0042492598/rust/property-defs-rs/src/types.rs#L457-L461
const DJANGO_MAX_CHARFIELD_LENGTH = 200

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

const DATE_PROP_KEYWORDS: string[] = ['time', 'timestamp', 'date', '_at', '-at', 'createdat', 'updatedat']

export const getPropertyType = (rawKey: string, value: any): PropertyType | null => {
    const key = rawKey.trim().toLowerCase()

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
        if (s === 'true' || s === 'false') {
            return PropertyType.Boolean
        }
        // Try to parse this as an ISO 8601 date
        try {
            if (DATE_PROP_KEYWORDS.some((kw) => key.includes(kw))) {
                return PropertyType.DateTime
            }
            const date = DateTime.fromISO(s)
            if (date.isValid) {
                return PropertyType.DateTime
            }
            // TODO(eli): add speculative date string matching?
        } catch {
            // Not a valid date, continue to string type
        }
        return PropertyType.String
    }

    if (typeof value === 'boolean') {
        return PropertyType.Boolean
    }

    if (typeof value === 'number') {
        if (value >= sixMonthsAgoUnixSeconds()) {
            return PropertyType.DateTime
        }
        return PropertyType.Numeric
    }

    return null
}

function willFitInPostgres(s: string) {
    return s.length < DJANGO_MAX_CHARFIELD_LENGTH
}

function sanitizeEventName(eventName: string) {
    return eventName.replace('\u0000', '\uFFFD')
}

function sixMonthsAgoUnixSeconds() {
    const now = new Date()
    now.setMonth(now.getMonth() - 6)
    return Math.floor(now.getTime() / 1000)
}

/**
 * NOTE: This is currently experimental and only used to do some testing on performance and comparisons.
 */
export class PropertyDefsConsumer {
    protected groupId: string
    protected topic: string
    protected name = 'property-defs-consumer'

    private batchConsumer?: BatchConsumer
    private propertyDefsDB: PropertyDefsDB
    private isStopping = false
    protected heartbeat = () => {}
    protected promises: Set<Promise<any>> = new Set()

    constructor(private hub: Hub) {
        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = hub.PROPERTY_DEFS_CONSUMER_GROUP_ID
        this.topic = hub.PROPERTY_DEFS_CONSUMER_CONSUME_TOPIC
        this.propertyDefsDB = new PropertyDefsDB(hub)
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
            Promise.resolve(this.extractPropertyDefinitions(parsedMessages))
        )

        for (const eventDef of Object.values(collected.eventDefinitionsById)) {
            eventDefTypesCounter.inc()
            console.log(eventDef) // TODO(eli): temp: make linter happy
            // TODO(eli): write it!
        }

        for (const propDef of Object.values(collected.propertyDefinitionsById)) {
            propertyDefTypesCounter.inc({ type: propDef.property_type ?? 'null' })
            // TODO(eli): write it!
        }

        for (const eventProp of Object.values(collected.eventPropertiesById)) {
            eventPropTypesCounter.inc()
            console.log(eventProp) // TODO(eli): temp: make linter happy
            // TODO(eli): write it!
        }

        status.debug('🔁', `Waiting for promises`, { promises: this.promises.size })
        await this.runInstrumented('awaitScheduledWork', () => Promise.all(this.promises))
        status.debug('🔁', `Processed batch`)
    }

    private extractPropertyDefinitions(events: ClickHouseEvent[]): CollectedPropertyDefinitions {
        const collected: CollectedPropertyDefinitions = {
            // TODO(eli): look these up in batches as pre-write step
            teamIdsInBatch: new Set<number>(),
            // TODO(eli): look these up in batches to resolve group types as pre-write step
            teamIdsWithGroupUpdatesInBatch: new Set<number>(),
            // deduped from batch, written to posthog_eventdefinition
            eventDefinitionsById: {},
            // deduped from batch, written to posthog_propertydefinition
            propertyDefinitionsById: {},
            // deduped from batch, written to posthog_eventproperty
            eventPropertiesById: {},
        }

        for (const event of events) {
            // these will be looked up later to trim write batches if team doesn't exist
            if (!collected.teamIdsInBatch.has(event.team_id)) {
                collected.teamIdsInBatch.add(event.team_id)
            }

            event.event = sanitizeEventName(event.event)

            if (!willFitInPostgres(event.event)) {
                propDefDroppedCounter.inc({ type: 'event', reason: 'key_too_long' })
                continue
            }

            const eventDefIdKey: string = `${event.team_id}:${event.event}`

            if (!collected.eventDefinitionsById[eventDefIdKey]) {
                collected.eventDefinitionsById[eventDefIdKey] = {
                    id: eventDefIdKey,
                    name: event.event,
                    team_id: event.team_id,
                    project_id: event.team_id, // TODO: add project_id
                    created_at: event.created_at.toISO() || DateTime.now().toString(),
                    volume_30_day: 0, // deprecated
                    query_usage_30_day: 0, // deprecated
                }
            }

            // Detect group identify events
            if (event.event === '$groupidentify') {
                if (!collected.teamIdsWithGroupUpdatesInBatch.has(event.team_id)) {
                    collected.teamIdsWithGroupUpdatesInBatch.add(event.team_id)
                }

                // bail on this event if there's no group type assigned
                const groupType: string | undefined = event.properties['$group_type'] // e.g. "organization"
                if (typeof groupType === 'undefined') {
                    continue
                }

                const groupProperties: Record<string, any> | undefined = event.properties['$group_set'] // { name: 'value', id: 'id', foo: "bar" }
                for (const [property, value] of Object.entries(groupProperties ?? {})) {
                    if (!willFitInPostgres(property)) {
                        propDefDroppedCounter.inc({ type: 'group', reason: 'key_too_long' })
                        continue
                    }

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
                            type: PropertyDefinitionTypeEnum.Group,
                            group_type_name: groupType,
                            group_type_index: 0, // TODO(eli): resolve these w/DB query on team_id using "groupType"
                        }
                    }
                }

                continue
            }

            // Detect person properties
            for (const [property, value] of Object.entries(event.person_properties ?? {})) {
                if (!willFitInPostgres(property)) {
                    propDefDroppedCounter.inc({ type: 'person', reason: 'key_too_long' })
                    continue
                }

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
                if (!willFitInPostgres(property)) {
                    propDefDroppedCounter.inc({ type: 'event', reason: 'key_too_long' })
                    continue
                }

                if (SKIP_PROPERTIES.includes(property)) {
                    // We don't need to count these as it is expected that they will be dropped
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

                const eventPropId = `${event.team_id}:${event.event}:${property}`

                if (!collected.eventPropertiesById[eventPropId]) {
                    collected.eventPropertiesById[eventPropId] = {
                        id: eventPropId,
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
