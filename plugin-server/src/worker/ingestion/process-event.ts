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
    PersonMode,
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
import { castTimestampOrNow } from '../../utils/utils'
import { GroupTypeManager, MAX_GROUP_TYPES_PER_TEAM } from './group-type-manager'
import { addGroupProperties } from './groups'
import { upsertGroup } from './properties-updater'
import { GroupAndFirstEventManager } from './property-definitions-manager'
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
    groupAndFirstEventManager: GroupAndFirstEventManager

    constructor(pluginsServer: Hub) {
        this.pluginsServer = pluginsServer
        this.db = pluginsServer.db
        this.clickhouse = pluginsServer.clickhouse
        this.kafkaProducer = pluginsServer.kafkaProducer
        this.teamManager = pluginsServer.teamManager
        this.groupTypeManager = new GroupTypeManager(pluginsServer.postgres, this.teamManager, pluginsServer.SITE_URL)
        this.groupAndFirstEventManager = new GroupAndFirstEventManager(
            this.teamManager,
            this.groupTypeManager,
            pluginsServer.db
        )
    }

    public async processEvent(
        distinctId: string,
        data: PluginEvent,
        teamId: number,
        timestamp: DateTime,
        eventUuid: string,
        processPerson: boolean
    ): Promise<PreIngestionEvent> {
        const singleSaveTimer = new Date()
        const timeout = timeoutGuard(
            'Still inside "EventsProcessor.processEvent". Timeout warning after 30 sec!',
            () => ({ event: JSON.stringify(data) })
        )

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
                result = await this.capture(
                    eventUuid,
                    team,
                    data['event'],
                    distinctId,
                    properties,
                    timestamp,
                    processPerson
                )
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
        timestamp: DateTime,
        processPerson: boolean
    ): Promise<PreIngestionEvent> {
        event = sanitizeEventName(event)

        if (properties['$ip'] && team.anonymize_ips) {
            delete properties['$ip']
        }

        if (this.pluginsServer.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP === false) {
            try {
                await this.groupAndFirstEventManager.updateGroupsAndFirstEvent(team.id, event, properties)
            } catch (err) {
                Sentry.captureException(err, { tags: { team_id: team.id } })
                status.warn('⚠️', 'Failed to update property definitions for an event', {
                    event,
                    properties,
                    err,
                })
            }
        }

        if (processPerson) {
            // Adds group_0 etc values to properties
            properties = await addGroupProperties(team.id, properties, this.groupTypeManager)

            if (event === '$groupidentify') {
                await this.upsertGroup(team.id, properties, timestamp)
            }
        }

        return {
            eventUuid,
            event,
            distinctId,
            properties,
            timestamp: timestamp.toISO() as ISOTimestamp,
            teamId: team.id,
        }
    }

    getGroupIdentifiers(properties: Properties): GroupId[] {
        const res: GroupId[] = []
        for (let groupTypeIndex = 0; groupTypeIndex < MAX_GROUP_TYPES_PER_TEAM; ++groupTypeIndex) {
            const key = `$group_${groupTypeIndex}`
            if (key in properties) {
                res.push([groupTypeIndex as GroupTypeIndex, properties[key]])
            }
        }
        return res
    }

    createEvent(
        preIngestionEvent: PreIngestionEvent,
        person: Person,
        processPerson: boolean
    ): [RawClickHouseEvent, Promise<void>] {
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

        let eventPersonProperties = '{}'
        if (processPerson) {
            eventPersonProperties = JSON.stringify({
                ...person.properties,
                // For consistency, we'd like events to contain the properties that they set, even if those were changed
                // before the event is ingested.
                ...(properties.$set || {}),
            })
        } else {
            // TODO: Move this into `normalizeEventStep` where it belongs, but the code structure
            // and tests demand this for now.
            for (let groupTypeIndex = 0; groupTypeIndex < MAX_GROUP_TYPES_PER_TEAM; ++groupTypeIndex) {
                const key = `$group_${groupTypeIndex}`
                delete properties[key]
            }
        }

        let personMode: PersonMode = 'full'
        if (person.force_upgrade) {
            personMode = 'force_upgrade'
        } else if (!processPerson) {
            personMode = 'propertyless'
        }

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
            person_properties: eventPersonProperties,
            person_created_at: castTimestampOrNow(person.created_at, TimestampFormat.ClickHouseSecondPrecision),
            person_mode: personMode,
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
                    await captureIngestionWarning(this.db.kafkaProducer, teamId, 'message_size_too_large', {
                        eventUuid: uuid,
                        distinctId: distinctId,
                    })
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
