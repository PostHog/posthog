import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { buildIntegerMatcher } from '../config/config'
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
    ProjectId,
    PropertyDefinitionType,
    PropertyDefinitionTypeEnum,
    PropertyType,
    RawClickHouseEvent,
    ValueMatcher,
} from '../types'
import { parseRawClickHouseEvent } from '../utils/event'
import { status } from '../utils/status'
import { UUIDT } from '../utils/utils'
import { GroupTypeManager, GroupTypesByProjectId } from '../worker/ingestion/group-type-manager'
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

const propDefsPostgresWritesCounter = new Counter({
    name: 'prop_defs_postgres_writes_total',
    help: 'Count of property definitions written to Postgres.',
    labelNames: ['type'],
})

export type CollectedPropertyDefinitions = {
    // known project ID => resolved group_type & group_type_index
    eventDefinitionsById: Record<ProjectId, Record<string, EventDefinitionType>>
    // known project ID => deduped properties
    propertyDefinitionsById: Record<ProjectId, Record<string, PropertyDefinitionType>>
    // known project ID => deduped event_properties
    eventPropertiesById: Record<ProjectId, Record<string, EventPropertyType>>
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
    private propDefsEnabledProjects: ValueMatcher<number>
    private writeDisabled: boolean

    constructor(private hub: Hub) {
        this.groupId = hub.PROPERTY_DEFS_CONSUMER_GROUP_ID
        this.topic = hub.PROPERTY_DEFS_CONSUMER_CONSUME_TOPIC
        this.propertyDefsDB = new PropertyDefsDB(hub)
        this.teamManager = new TeamManager(hub.postgres)
        this.groupTypeManager = new GroupTypeManager(hub.postgres, this.teamManager)
        this.propDefsEnabledProjects = buildIntegerMatcher(hub.PROPERTY_DEFS_CONSUMER_ENABLED_TEAMS, true)
        this.writeDisabled = hub.PROPERTY_DEFS_WRITE_DISABLED
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
        let parsedMessages: ClickHouseEvent[] = await this.runInstrumented('parseKafkaMessages', () =>
            this.parseKafkaBatch(messages)
        )

        parsedMessages = parsedMessages.filter((msg) => this.propDefsEnabledProjects(msg.project_id))

        if (parsedMessages.length === 0) {
            status.debug('🔁', `No messages to process`)
            return
        }

        const projectsToLoadGroupsFor = new Set<ProjectId>()

        parsedMessages.forEach((msg) => {
            if (msg.event === '$groupidentify') {
                projectsToLoadGroupsFor.add(msg.project_id)
            }
        })

        const groupTypesByProjectId = await this.runInstrumented('fetchGroupTypesForProjects', () =>
            this.groupTypeManager.fetchGroupTypesForProjects(projectsToLoadGroupsFor)
        )

        // extract and dedup event and property definitions
        const collected = await this.runInstrumented('derivePropDefs', () =>
            Promise.resolve(this.extractPropertyDefinitions(parsedMessages, groupTypesByProjectId))
        )

        const eventDefinitions = Object.values(collected.eventDefinitionsById).flatMap((eventDefinitions) =>
            Object.values(eventDefinitions)
        )

        if (eventDefinitions.length > 0) {
            eventDefTypesCounter.inc(eventDefinitions.length)
            status.info('🔁', `Writing event definitions batch of size ${eventDefinitions.length}`)
            propDefsPostgresWritesCounter.inc({ type: 'event_definitions' })
            if (!this.writeDisabled) {
                void this.scheduleWork(this.propertyDefsDB.writeEventDefinitions(eventDefinitions))
            }
        }

        const propertyDefinitions = Object.values(collected.propertyDefinitionsById).flatMap((propertyDefinitions) =>
            Object.values(propertyDefinitions)
        )

        if (propertyDefinitions.length > 0) {
            for (const propDef of propertyDefinitions) {
                propertyDefTypesCounter.inc({ type: propDef.type })
            }
            status.info('🔁', `Writing property definitions batch of size ${propertyDefinitions.length}`)
            propDefsPostgresWritesCounter.inc({ type: 'property_definitions' })
            if (!this.writeDisabled) {
                void this.scheduleWork(this.propertyDefsDB.writePropertyDefinitions(propertyDefinitions))
            }
        }

        const eventProperties = Object.values(collected.eventPropertiesById).flatMap((eventProperties) =>
            Object.values(eventProperties)
        )

        if (eventProperties.length > 0) {
            eventPropTypesCounter.inc(eventProperties.length)
            status.info('🔁', `Writing event properties batch of size ${eventProperties.length}`)
            propDefsPostgresWritesCounter.inc({ type: 'event_properties' })
            if (!this.writeDisabled) {
                void this.scheduleWork(this.propertyDefsDB.writeEventProperties(eventProperties))
            }
        }

        status.debug('🔁', `Waiting for promises`, { promises: this.promises.size })
        await this.runInstrumented('awaitScheduledWork', () => Promise.all(this.promises))
        status.debug('🔁', `Processed batch`)
    }

    private extractPropertyDefinitions(
        events: ClickHouseEvent[],
        groupTypesByProjectId: GroupTypesByProjectId
    ): CollectedPropertyDefinitions {
        const collected: CollectedPropertyDefinitions = {
            eventDefinitionsById: {},
            propertyDefinitionsById: {},
            eventPropertiesById: {},
        }

        for (const event of events) {
            event.event = sanitizeEventName(event.event)

            if (!willFitInPostgres(event.event)) {
                propDefDroppedCounter.inc({ type: 'event', reason: 'key_too_long' })
                continue
            }

            // Setup all the objects for this event's project ID
            const eventDefinitions = (collected.eventDefinitionsById[event.project_id] =
                collected.eventDefinitionsById[event.project_id] ?? {})

            const propertyDefinitions = (collected.propertyDefinitionsById[event.project_id] =
                collected.propertyDefinitionsById[event.project_id] ?? {})

            const eventProperties = (collected.eventPropertiesById[event.project_id] =
                collected.eventPropertiesById[event.project_id] ?? {})

            // Capture event definition
            if (!eventDefinitions[event.event]) {
                eventDefinitions[event.event] = {
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

            const groupTypesForProject = groupTypesByProjectId[event.project_id]
            if (event.event === '$groupidentify') {
                // bail if the team ID doesn't exist in posthog_team
                if (!groupTypesForProject) {
                    propDefDroppedCounter.inc({ type: 'group', reason: 'team_groups_not_found' })
                    shouldCaptureGroupProps = false
                }

                // bail if there's no group type assigned to the event
                if (!event.properties['$group_type']) {
                    propDefDroppedCounter.inc({ type: 'group', reason: 'undefined_group' })
                    shouldCaptureGroupProps = false
                }

                // bail if the group type on the event was not resolved to an index in posthog_grouptypemappings
                if (!groupTypesForProject?.[event.properties['$group_type']]) {
                    propDefDroppedCounter.inc({ type: 'group', reason: 'group_index_not_found' })
                    shouldCaptureGroupProps = false
                }
            }

            // Capture group properties
            if (shouldCaptureGroupProps && groupTypesForProject) {
                const groupType: string = event.properties['$group_type'] // e.g. "organization"
                const groupTypeIndex = groupTypesForProject[groupType]
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

                    const propDefKey = `${groupType}:${property}`
                    if (!propertyDefinitions[propDefKey]) {
                        propertyDefinitions[propDefKey] = {
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
                if (!propertyDefinitions[propDefKey]) {
                    const propType = getPropertyType(property, value)
                    if (propType) {
                        propertyDefinitions[propDefKey] = {
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
                if (!propertyDefinitions[propDefKey]) {
                    const propType = getPropertyType(property, value)
                    if (propType) {
                        propertyDefinitions[propDefKey] = {
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
                if (!eventProperties[eventPropKey]) {
                    eventProperties[eventPropKey] = {
                        id: new UUIDT().toString(),
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
