import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Counter, Summary } from 'prom-client'

import { KafkaProducerWrapper } from '../../kafka/producer'
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
import { safeClickhouseString, sanitizeEventName, timeoutGuard } from '../../utils/db/utils'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { castTimestampOrNow } from '../../utils/utils'
import { GroupTypeManager, MAX_GROUP_TYPES_PER_TEAM } from './group-type-manager'
import { addGroupProperties } from './groups'
import { upsertGroup } from './properties-updater'
import { TeamManager } from './team-manager'
import { captureIngestionWarning } from './utils'

// for e.g. internal events we don't want to be available for users in the UI
const EVENTS_WITHOUT_EVENT_DEFINITION = ['$$plugin_metrics']

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

const updateEventNamesAndPropertiesMsSummary = new Summary({
    name: 'update_event_names_and_properties_ms',
    help: 'Duration spent in updateEventNamesAndProperties',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export class EventsProcessor {
    private db: DB
    private kafkaProducer: KafkaProducerWrapper
    private teamManager: TeamManager
    private groupTypeManager: GroupTypeManager

    constructor(private hub: Hub) {
        this.db = hub.db
        this.kafkaProducer = hub.kafkaProducer
        this.teamManager = hub.teamManager
        this.groupTypeManager = hub.groupTypeManager
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

        if (this.hub.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP === false) {
            try {
                await this.updateGroupsAndFirstEvent(team, event, properties)
            } catch (err) {
                captureException(err, { tags: { team_id: team.id } })
                logger.warn('⚠️', 'Failed to update property definitions for an event', {
                    event,
                    properties,
                    err,
                })
            }
        }

        if (processPerson) {
            // Adds group_0 etc values to properties
            properties = await addGroupProperties(team, properties, this.groupTypeManager)

            if (event === '$groupidentify') {
                await this.upsertGroup(team, properties, timestamp)
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

    createEvent(preIngestionEvent: PreIngestionEvent, person: Person, processPerson: boolean): RawClickHouseEvent {
        const { eventUuid: uuid, event, teamId, distinctId, properties, timestamp } = preIngestionEvent

        let elementsChain = ''
        try {
            elementsChain = this.getElementsChain(properties)
        } catch (error) {
            captureException(error, { tags: { team_id: teamId } })
            logger.warn('⚠️', 'Failed to process elements', {
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

        return rawEvent
    }

    emitEvent(rawEvent: RawClickHouseEvent, team: Team): Promise<void> {
        // NOTE: We add extra properties to the produced event as the prop-defs service needs them
        const kafkaEvent: RawClickHouseEvent & { project_id: number; root_project_id: number } = {
            ...rawEvent,
            // NOTE: project_id will be removed once the service is updated using the new root_project_id
            project_id: team.root_team_id,
            root_project_id: team.root_team_id,
        }

        return this.kafkaProducer
            .produce({
                topic: this.hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                key: rawEvent.uuid,
                value: Buffer.from(JSON.stringify(kafkaEvent)),
            })
            .catch(async (error) => {
                // Some messages end up significantly larger than the original
                // after plugin processing, person & group enrichment, etc.
                if (error instanceof MessageSizeTooLarge) {
                    await captureIngestionWarning(this.db.kafkaProducer, rawEvent.team_id, 'message_size_too_large', {
                        eventUuid: rawEvent.uuid,
                        distinctId: rawEvent.distinct_id,
                    })
                } else {
                    throw error
                }
            })
    }

    private async upsertGroup(team: Team, properties: Properties, timestamp: DateTime): Promise<void> {
        if (!properties['$group_type'] || !properties['$group_key']) {
            return
        }

        const { $group_type: groupType, $group_key: groupKey, $group_set: groupPropertiesToSet } = properties
        const groupTypeIndex = await this.groupTypeManager.fetchGroupTypeIndex(team, groupType)

        if (groupTypeIndex !== null) {
            await upsertGroup(
                this.db,
                team.id,
                groupTypeIndex,
                groupKey.toString(),
                groupPropertiesToSet || {},
                timestamp
            )
        }
    }

    private async updateGroupsAndFirstEvent(team: Team, event: string, properties: Properties): Promise<void> {
        if (EVENTS_WITHOUT_EVENT_DEFINITION.includes(event)) {
            return
        }

        const timer = new Date()
        const timeout = timeoutGuard(
            'Still running "updateEventNamesAndProperties". Timeout warning after 30 sec!',
            () => ({
                event: event,
            })
        )

        try {
            // We always track 1st event ingestion
            const promises: Promise<any>[] = [this.teamManager.setTeamIngestedEvent(team, properties)]

            // We always insert/update group-types, so if this is a group-identify event, we hit
            // the group-type manager, making it insert or update as necessary.
            if (event === '$groupidentify') {
                const { $group_type: groupType, $group_set: groupPropertiesToSet } = properties
                if (groupType != null && groupPropertiesToSet != null) {
                    // This "fetch" is side-effecty, it inserts a group-type and assigns an index if one isn't found
                    promises.push(this.groupTypeManager.fetchGroupTypeIndex(team, groupType))
                }
            }

            await Promise.all(promises)
        } finally {
            clearTimeout(timeout)
            updateEventNamesAndPropertiesMsSummary.observe(Date.now() - timer.valueOf())
        }
    }
}
