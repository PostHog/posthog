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
    ResolvedGroups,
} from '../types'
import { parseRawClickHouseEvent } from '../utils/event'
import { status } from '../utils/status'
import { PropertyDefsDB } from './services/property-defs-db'
import {
    getPropertyType,
    PROPERTY_DEFS_PROPERTIES_TO_SKIP,
    sanitizeEventName,
    willFitInPostgres,
} from './services/property-defs-utils'

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
    knownTeamIds: Set<number>
    resolvedTeamGroups: Record<number, ResolvedGroups>
    eventDefinitionsById: Record<string, EventDefinitionType>
    propertyDefinitionsById: Record<string, PropertyDefinitionType>
    eventPropertiesById: Record<string, EventPropertyType>
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

        const collected: CollectedPropertyDefinitions = {
            // resolved prior to prop extraction; used to filter events/props w/o parent team
            knownTeamIds: new Set<number>(),
            // resolved prior to prop extraction; used to filter group updates w/o team or registered groups
            resolvedTeamGroups: {},
            // deduped from batch, written to posthog_eventdefinition
            eventDefinitionsById: {},
            // deduped from batch, written to posthog_propertydefinition
            propertyDefinitionsById: {},
            // deduped from batch, written to posthog_eventproperty
            eventPropertiesById: {},
        }

        const teamsInBatch = this.extractTeamIds(parsedMessages)
        collected.knownTeamIds = await this.runInstrumented('resolveTeams', () =>
            Promise.resolve(this.resolveTeams(this.propertyDefsDB, teamsInBatch))
        )

        const groupTeamsInBatch = this.extractGroupTeamIds(parsedMessages, collected.knownTeamIds)
        collected.resolvedTeamGroups = await this.runInstrumented('resolveGroupsForTeams', () =>
            Promise.resolve(this.resolveGroupsForTeams(this.propertyDefsDB, groupTeamsInBatch))
        )

        console.log('🔁', `Event batch teams and group indices resolved`)

        // extract and dedup event and property definitions
        void (await this.runInstrumented('derivePropDefs', () =>
            Promise.resolve(this.extractPropertyDefinitions(parsedMessages, collected))
        ))

        console.log('🔁', `Property definitions collected`, JSON.stringify(collected, null, 2))

        for (const eventDef of Object.values(collected.eventDefinitionsById)) {
            eventDefTypesCounter.inc()
            status.info('🔁', `Writing event definition`, { eventDef })

            // TODO: Batch all these DB writes
            void this.scheduleWork(this.propertyDefsDB.writeEventDefinition(eventDef))
        }

        for (const propDef of Object.values(collected.propertyDefinitionsById)) {
            propertyDefTypesCounter.inc({ type: propDef.property_type ?? 'null' })
            status.info('🔁', `Writing property definition`, { propDef })

            // TODO: Batch all these DB writes
            void this.scheduleWork(this.propertyDefsDB.writePropertyDefinition(propDef))
        }

        for (const eventProp of Object.values(collected.eventPropertiesById)) {
            eventPropTypesCounter.inc()
            status.info('🔁', `Writing event property`, { eventProp })

            // TODO: Batch all these DB writes
            void this.scheduleWork(this.propertyDefsDB.writeEventProperty(eventProp))
        }

        status.debug('🔁', `Waiting for promises`, { promises: this.promises.size })
        await this.runInstrumented('awaitScheduledWork', () => Promise.all(this.promises))
        status.debug('🔁', `Processed batch`)
    }

    private async resolveTeams(db: PropertyDefsDB, teamIdsInBatch: Set<number>): Promise<Set<number>> {
        const teamsFound = await db.findTeamIds(Array.from(teamIdsInBatch))
        return new Set(teamsFound.filter((row) => !teamIdsInBatch.has(row.teamId)).map((row) => row.teamId))
    }

    private async resolveGroupsForTeams(
        db: PropertyDefsDB,
        knownTeamIdsWithGroup: Set<number>
    ): Promise<Record<number, ResolvedGroups>> {
        const result = await db.resolveGroupsForTeams(Array.from(knownTeamIdsWithGroup))

        const out: Record<number, ResolvedGroups> = {}
        result.forEach((row) => {
            let resolved: ResolvedGroups
            if (out[row.teamId]) {
                resolved = out[row.teamId]
            } else {
                resolved = {}
            }

            resolved[row.groupName] = row.groupIndex
            out[row.teamId] = resolved
        })

        return out
    }

    private extractTeamIds(events: ClickHouseEvent[]): Set<number> {
        return new Set(events.map((event) => event.team_id))
    }

    private extractGroupTeamIds(events: ClickHouseEvent[], knownTeamIds: Set<number>): Set<number> {
        return new Set(
            events
                .filter((event) => event.event == '$groupidentify' && knownTeamIds.has(event.team_id))
                .map((event) => event.team_id)
        )
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
                if (!collected.resolvedTeamGroups[event.team_id]) {
                    propDefDroppedCounter.inc({ type: 'event', reason: 'team_groups_not_found' })
                    continue
                }

                // bail on this event if there's no group type assigned or we couldn't resolve it's index
                const groupType: string | undefined = event.properties['$group_type'] // e.g. "organization"
                if (typeof groupType === 'undefined' || !collected.resolvedTeamGroups[event.team_id][groupType]) {
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

                if (PROPERTY_DEFS_PROPERTIES_TO_SKIP.includes(property)) {
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
