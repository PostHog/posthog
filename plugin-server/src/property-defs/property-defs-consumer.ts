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
    GroupTypeToColumnIndex,
    Hub,
    PluginServerService,
    PropertyDefinitionType,
    PropertyDefinitionTypeEnum,
    PropertyType,
    RawClickHouseEvent,
    TeamId,
} from '../types'
import { parseRawClickHouseEvent } from '../utils/event'
import { status } from '../utils/status'
import { UUIDT } from '../utils/utils'
import { GroupTypeManager } from '../worker/ingestion/group-type-manager'
import { TeamManager } from '../worker/ingestion/team-manager'
import { PropertyDefsDB } from './services/property-defs-db'
import {
    getPropertyType,
    PROPERTY_DEFS_PROPERTIES_TO_SKIP,
    sanitizeEventName,
    willFitInPostgres,
} from './services/property-defs-utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

const BATCH_SIZE = 100

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
    // looked up prior to event/prop extraction
    knownTeamIds: Set<number>
    // looked up prior to event/prop extraction. map of project_id => group_type => group_index
    resolvedTeamGroups: Record<number, GroupTypeToColumnIndex>
    // known team ID => resolved group_type & group_type_index
    eventDefinitionsById: Record<number, Record<string, EventDefinitionType>>
    // known team ID => deduped properties
    propertyDefinitionsById: Record<number, Record<string, PropertyDefinitionType>>
    // known team ID => deduped event_properties
    eventPropertiesById: Record<number, Record<string, EventPropertyType>>
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
    private teamManager: TeamManager
    private groupTypeManager: GroupTypeManager
    private isStopping = false
    protected heartbeat = () => {}
    protected promises: Set<Promise<any>> = new Set()

    constructor(private hub: Hub) {
        this.groupId = hub.PROPERTY_DEFS_CONSUMER_GROUP_ID
        this.topic = hub.PROPERTY_DEFS_CONSUMER_CONSUME_TOPIC
        this.propertyDefsDB = new PropertyDefsDB(hub)
        this.teamManager = new TeamManager(hub.postgres)
        this.groupTypeManager = new GroupTypeManager(hub.postgres, this.teamManager)
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
        const parsedMessages: ClickHouseEvent[] = await this.runInstrumented('parseKafkaMessages', () =>
            this.parseKafkaBatch(messages)
        )

        // used to filter and dedup to minimum batch of writable records
        const collected: CollectedPropertyDefinitions = {
            knownTeamIds: new Set<number>(),
            resolvedTeamGroups: {},
            eventDefinitionsById: {},
            propertyDefinitionsById: {},
            eventPropertiesById: {},
        }

        const eventTeamIds = parsedMessages.map((msg) => msg.team_id as TeamId)
        const groupTeamIds = parsedMessages.filter((msg) => msg.event == '$groupidentify').map((msg) => msg.team_id)

        const [knownTeamIds, resolvedProjectGroups] = await Promise.all([
            this.runInstrumented('resolveTeams', () => this.teamManager.validateTeamIds(eventTeamIds)),
            this.runInstrumented('resolveProjectGroupTypeIndices', () =>
                this.groupTypeManager.fetchGroupTypesIndicesForTeams(groupTeamIds)
            ),
        ])

        collected.knownTeamIds = new Set(knownTeamIds)
        collected.resolvedTeamGroups = resolvedProjectGroups

        console.log('🔁', `Event batch teams and group indices resolved`)

        // extract and dedup event and property definitions
        await this.runInstrumented('derivePropDefs', () =>
            Promise.resolve(this.extractPropertyDefinitions(parsedMessages, collected))
        )

        console.log('🔁', `Property definitions collected`, JSON.stringify(collected, null, 2))

        for (const knownTeamId in collected.eventDefinitionsById) {
            let buffer: EventDefinitionType[] = []
            for (const key in collected.eventDefinitionsById[knownTeamId]) {
                const eventDef = collected.eventDefinitionsById[knownTeamId][key]
                buffer.push(eventDef)
                eventDefTypesCounter.inc()

                if (buffer.length === BATCH_SIZE) {
                    status.info('🔁', `Writing event definition batch of size ${buffer.length}`)
                    void this.scheduleWork(this.propertyDefsDB.writeEventDefinitionsBatch(buffer))
                    buffer = []
                }
            }
        }

        for (const knownTeamId in collected.propertyDefinitionsById) {
            let buffer: PropertyDefinitionType[] = []
            for (const key in collected.propertyDefinitionsById[knownTeamId]) {
                const propDef: PropertyDefinitionType = collected.propertyDefinitionsById[knownTeamId][key]
                buffer.push(propDef)
                propertyDefTypesCounter.inc({ type: propDef.property_type?.toString() ?? 'unknown' })

                if (buffer.length === BATCH_SIZE) {
                    status.info('🔁', `Writing property definitions batch of size ${buffer.length}`)
                    void this.scheduleWork(this.propertyDefsDB.writePropertyDefinitionsBatch(buffer))
                    buffer = []
                }
            }
        }

        for (const knownTeamId in collected.eventPropertiesById) {
            let buffer: EventPropertyType[] = []
            for (const key in collected.eventPropertiesById[knownTeamId]) {
                const eventProp = collected.eventPropertiesById[knownTeamId][key]
                eventPropTypesCounter.inc()
                buffer.push(eventProp)

                if (buffer.length === BATCH_SIZE) {
                    status.info('🔁', `Writing event properties batch of size ${buffer.length}`)
                    void this.scheduleWork(this.propertyDefsDB.writeEventPropertiesBatch(buffer))
                    buffer = []
                }
            }
        }

        status.debug('🔁', `Waiting for promises`, { promises: this.promises.size })
        await this.runInstrumented('awaitScheduledWork', () => Promise.all(this.promises))
        status.debug('🔁', `Processed batch`)
    }

    private extractPropertyDefinitions(events: ClickHouseEvent[], collected: CollectedPropertyDefinitions) {
        for (const event of events) {
            if (!collected.knownTeamIds.has(event.team_id)) {
                propDefDroppedCounter.inc({ type: 'event', reason: 'team_id_not_found' })
                continue
            }
            event.event = sanitizeEventName(event.event)

            if (!willFitInPostgres(event.event)) {
                propDefDroppedCounter.inc({ type: 'event', reason: 'key_too_long' })
                continue
            }

            if (!collected.eventDefinitionsById[event.team_id]) {
                collected.eventDefinitionsById[event.team_id] = {}
            }

            // Capture event definition
            if (!collected.eventDefinitionsById[event.team_id][event.event]) {
                collected.eventDefinitionsById[event.team_id][event.event] = {
                    id: new UUIDT().toString(),
                    name: event.event,
                    team_id: event.team_id,
                    project_id: event.team_id, // TODO: add project_id
                    created_at: event.created_at.toISO() || DateTime.now().toString(),
                    volume_30_day: 0, // deprecated
                    query_usage_30_day: 0, // deprecated
                }
            }

            // Decision: are there group properties eligible for capture in this event?
            let shouldCaptureGroupProps: boolean = true
            if (event.event === '$groupidentify') {
                // bail if the team ID doesn't exist in posthog_team
                if (!collected.resolvedTeamGroups[event.team_id]) {
                    propDefDroppedCounter.inc({ type: 'group', reason: 'team_groups_not_found' })
                    shouldCaptureGroupProps = false
                }

                // bail if there's no group type assigned to the event
                if (!event.properties['$group_type']) {
                    propDefDroppedCounter.inc({ type: 'group', reason: 'undefined_group' })
                    shouldCaptureGroupProps = false
                }

                // bail if the group type on the event was not resolved to an index in posthog_grouptypemappings
                if (!collected.resolvedTeamGroups[event.team_id][event.properties['$group_type']]) {
                    propDefDroppedCounter.inc({ type: 'group', reason: 'group_index_not_found' })
                    shouldCaptureGroupProps = false
                }
            }

            // Capture group properties
            if (shouldCaptureGroupProps) {
                const groupType: string = event.properties['$group_type'] // e.g. "organization"
                const groupProperties: Record<string, any> | undefined = event.properties['$group_set'] // { name: 'value', id: 'id', foo: "bar" }

                for (const [property, value] of Object.entries(groupProperties ?? {})) {
                    if (!willFitInPostgres(property)) {
                        propDefDroppedCounter.inc({ type: 'group', reason: 'key_too_long' })
                        continue
                    }

                    const propType = getPropertyType(property, value)
                    if (!propType) {
                        propDefDroppedCounter.inc({ type: 'group', reason: 'missing_prop_type' })
                        continue
                    }

                    const groupTypeIndex = collected.resolvedTeamGroups[event.team_id][groupType]
                    const propDefKey = `${groupType}:${property}`
                    if (!collected.propertyDefinitionsById[event.team_id][propDefKey]) {
                        collected.propertyDefinitionsById[event.team_id][propDefKey] = {
                            id: new UUIDT().toString(),
                            name: property,
                            is_numerical: propType === PropertyType.Numeric,
                            team_id: event.team_id,
                            project_id: event.team_id, // TODO: Add project_id
                            property_type: propType,
                            type: PropertyDefinitionTypeEnum.Group,
                            group_type_name: groupType,
                            group_type_index: groupTypeIndex,
                        }
                    }
                }
            }

            // Capture person properties
            for (const [property, value] of Object.entries(event.person_properties ?? {})) {
                if (!willFitInPostgres(property)) {
                    propDefDroppedCounter.inc({ type: 'person', reason: 'key_too_long' })
                    continue
                }

                const propDefKey = `person:${property}`
                if (!collected.propertyDefinitionsById[event.team_id][propDefKey]) {
                    const propType = getPropertyType(property, value)
                    if (propType) {
                        collected.propertyDefinitionsById[event.team_id][propDefKey] = {
                            id: new UUIDT().toString(),
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

            // Capture event properties
            for (const [property, value] of Object.entries(event.properties)) {
                if (!willFitInPostgres(property)) {
                    propDefDroppedCounter.inc({ type: 'event', reason: 'key_too_long' })
                    continue
                }

                if (PROPERTY_DEFS_PROPERTIES_TO_SKIP.includes(property)) {
                    // We don't need to count these as it is expected that they will be dropped
                    continue
                }

                const propDefKey = `event:${property}`
                if (!collected.propertyDefinitionsById[event.team_id][propDefKey]) {
                    const propType = getPropertyType(property, value)
                    if (propType) {
                        collected.propertyDefinitionsById[event.team_id][propDefKey] = {
                            id: new UUIDT().toString(),
                            name: property,
                            is_numerical: propType === PropertyType.Numeric,
                            team_id: event.team_id,
                            project_id: event.team_id, // TODO: Add project_id
                            property_type: propType,
                            type: PropertyDefinitionTypeEnum.Event,
                        }
                    }
                }

                const eventPropKey = `${event.event}:${property}`
                if (!collected.eventPropertiesById[event.team_id][eventPropKey]) {
                    collected.eventPropertiesById[event.team_id][eventPropKey] = {
                        id: new UUIDT().toString(),
                        event: event.event,
                        property,
                        team_id: event.team_id,
                        project_id: event.team_id, // TODO: Add project_id
                    }
                }
            }
        }
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
