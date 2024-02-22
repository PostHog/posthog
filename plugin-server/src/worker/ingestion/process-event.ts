import ClickHouse from '@posthog/clickhouse'
import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'
import { Counter, Summary } from 'prom-client'

import {
    Element,
    GroupTypeIndex,
    Hub,
    ISOTimestamp,
    Person,
    PreIngestionEvent,
    RawClickHouseEvent,
    Team,
    TimestampFormat,
} from '../../types'
import { DB, GroupId } from '../../utils/db/db'
import { elementsToString, extractElements } from '../../utils/db/elements-chain'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import { safeClickhouseString, sanitizeEventName, timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { MessageSizeTooLargeWarningLimiter } from '../../utils/token-bucket'
import { castTimestampOrNow } from '../../utils/utils'
import { GroupTypeManager } from './group-type-manager'
import { addGroupProperties } from './groups'
import { upsertGroup } from './properties-updater'
import { PropertyDefinitionsManager } from './property-definitions-manager'
import { TeamManager } from './team-manager'
import { captureIngestionWarning } from './utils'

const processEventMsSummary = new Summary({
    name: 'process_event_ms',
    help: 'Duration spent in processEvent',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

const elementsOrElementsChainCounter = new Counter({
    name: 'events_pipeline_elements_or_elements_chain_total',
    help: 'Number of times elements or elements_chain appears on event',
    labelNames: ['type'],
})

export class EventsProcessor {
    pluginsServer: Hub
    db: DB
    clickhouse: ClickHouse
    kafkaProducer: KafkaProducerWrapper
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    propertyDefinitionsManager: PropertyDefinitionsManager

    constructor(pluginsServer: Hub) {
        this.pluginsServer = pluginsServer
        this.db = pluginsServer.db
        this.clickhouse = pluginsServer.clickhouse
        this.kafkaProducer = pluginsServer.kafkaProducer
        this.teamManager = pluginsServer.teamManager
        this.groupTypeManager = new GroupTypeManager(pluginsServer.db, this.teamManager, pluginsServer.SITE_URL)
        this.propertyDefinitionsManager = new PropertyDefinitionsManager(
            this.teamManager,
            this.groupTypeManager,
            pluginsServer.db,
            pluginsServer
        )
    }

    public async processEvent(
        distinctId: string,
        data: PluginEvent,
        teamId: number,
        timestamp: DateTime,
        eventUuid: string
    ): Promise<[PreIngestionEvent, Promise<void>[]]> {
        const singleSaveTimer = new Date()
        const timeout = timeoutGuard('Still inside "EventsProcessor.processEvent". Timeout warning after 30 sec!', {
            event: JSON.stringify(data),
        })

        let result: PreIngestionEvent | null = null
        try {
            // We know `normalizeEvent` has been called here.
            const properties: Properties = data.properties!

            const team = await this.teamManager.fetchTeam(teamId)
            if (!team) {
                throw new Error(`No team found with ID ${teamId}. Can't ingest event.`)
            }

            const captureTimeout = timeoutGuard('Still running "capture". Timeout warning after 30 sec!', {
                eventUuid,
            })
            try {
                result = await this.capture(eventUuid, team, data['event'], distinctId, properties, timestamp)
                processEventMsSummary.observe(Date.now() - singleSaveTimer.valueOf())
            } finally {
                clearTimeout(captureTimeout)
            }
        } finally {
            clearTimeout(timeout)
        }
        return result
    }

    private getElementsChain(properties: Properties): string {
        /*
        We're deprecating $elements in favor of $elements_chain, which doesn't require extra
        processing on the ingestion side and is the way we store elements in ClickHouse.
        As part of that we'll move posthog-js to send us $elements_chain as string directly,
        but we still need to support the old way of sending $elements and converting them
        to $elements_chain, while everyone hasn't upgraded.
        */
        let elementsChain = ''
        if (properties['$elements_chain']) {
            elementsChain = properties['$elements_chain']
            elementsOrElementsChainCounter.labels('elements_chain').inc()
        } else if (properties['$elements']) {
            const elements: Record<string, any>[] | undefined = properties['$elements']
            let elementsList: Element[] = []
            if (elements && elements.length) {
                elementsList = extractElements(elements)
                elementsChain = elementsToString(elementsList)
            }
            elementsOrElementsChainCounter.labels('elements').inc()
        }
        delete properties['$elements_chain']
        delete properties['$elements']
        return elementsChain
    }

    private async capture(
        eventUuid: string,
        team: Team,
        event: string,
        distinctId: string,
        properties: Properties,
        timestamp: DateTime
    ): Promise<[PreIngestionEvent, Promise<void>[]]> {
        event = sanitizeEventName(event)

        if (properties['$ip'] && team.anonymize_ips) {
            delete properties['$ip']
        }

        const acks: Promise<void>[] = []

        if (this.pluginsServer.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP === false) {
            try {
                acks.push(this.propertyDefinitionsManager.updateEventNamesAndProperties(team.id, event, properties))
            } catch (err) {
                Sentry.captureException(err, { tags: { team_id: team.id } })
                status.warn('⚠️', 'Failed to update property definitions for an event', {
                    event,
                    properties,
                    err,
                })
            }
        }

        // Adds group_0 etc values to properties
        properties = await addGroupProperties(team.id, properties, this.groupTypeManager)

        if (event === '$groupidentify') {
            acks.push(this.upsertGroup(team.id, properties, timestamp))
        }

        return [
            {
                eventUuid,
                event,
                distinctId,
                properties,
                timestamp: timestamp.toISO() as ISOTimestamp,
                teamId: team.id,
            },
            acks,
        ]
    }

    getGroupIdentifiers(properties: Properties): GroupId[] {
        const res: GroupId[] = []
        for (let groupTypeIndex = 0; groupTypeIndex < this.db.MAX_GROUP_TYPES_PER_TEAM; ++groupTypeIndex) {
            const key = `$group_${groupTypeIndex}`
            if (key in properties) {
                res.push([groupTypeIndex as GroupTypeIndex, properties[key]])
            }
        }
        return res
    }

    async createEvent(
        preIngestionEvent: PreIngestionEvent,
        person: Person
    ): Promise<[RawClickHouseEvent, Promise<void>]> {
        const { eventUuid: uuid, event, teamId, distinctId, properties, timestamp } = preIngestionEvent

        let elementsChain = ''
        try {
            elementsChain = this.getElementsChain(properties)
        } catch (error) {
            Sentry.captureException(error, { tags: { team_id: teamId } })
            status.warn('⚠️', 'Failed to process elements', {
                uuid,
                teamId: teamId,
                properties,
                error,
            })
        }

        const groupIdentifiers = this.getGroupIdentifiers(properties)
        const groupsColumns = await this.db.getGroupsColumns(teamId, groupIdentifiers)

        const eventPersonProperties: string = JSON.stringify({
            ...person.properties,
            // For consistency, we'd like events to contain the properties that they set, even if those were changed
            // before the event is ingested.
            ...(properties.$set || {}),
        })
        // TODO: Remove Redis caching for person that's not used anymore

        const rawEvent: RawClickHouseEvent = {
            uuid,
            event: safeClickhouseString(event),
            properties: JSON.stringify(properties ?? {}),
            timestamp: castTimestampOrNow(timestamp, TimestampFormat.ClickHouse),
            team_id: teamId,
            distinct_id: safeClickhouseString(distinctId),
            elements_chain: safeClickhouseString(elementsChain),
            created_at: castTimestampOrNow(null, TimestampFormat.ClickHouse),
            person_id: person.uuid,
            person_properties: eventPersonProperties ?? undefined,
            person_created_at: castTimestampOrNow(person.created_at, TimestampFormat.ClickHouseSecondPrecision),
            ...groupsColumns,
        }

        const ack = this.kafkaProducer
            .produce({
                topic: this.pluginsServer.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                key: uuid,
                value: Buffer.from(JSON.stringify(rawEvent)),
                waitForAck: true,
            })
            .catch(async (error) => {
                // Some messages end up significantly larger than the original
                // after plugin processing, person & group enrichment, etc.
                if (error instanceof MessageSizeTooLarge) {
                    if (MessageSizeTooLargeWarningLimiter.consume(`${teamId}`, 1)) {
                        await captureIngestionWarning(this.db, teamId, 'message_size_too_large', {
                            eventUuid: uuid,
                            distinctId: distinctId,
                        })
                    }
                } else {
                    throw error
                }
            })

        return [rawEvent, ack]
    }

    private async upsertGroup(teamId: number, properties: Properties, timestamp: DateTime): Promise<void> {
        if (!properties['$group_type'] || !properties['$group_key']) {
            return
        }

        const { $group_type: groupType, $group_key: groupKey, $group_set: groupPropertiesToSet } = properties
        const groupTypeIndex = await this.groupTypeManager.fetchGroupTypeIndex(teamId, groupType)

        if (groupTypeIndex !== null) {
            await upsertGroup(
                this.db,
                teamId,
                groupTypeIndex,
                groupKey.toString(),
                groupPropertiesToSet || {},
                timestamp
            )
        }
    }
}
