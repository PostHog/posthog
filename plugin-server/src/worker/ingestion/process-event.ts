import { DateTime } from 'luxon'
import { Counter, Summary } from 'prom-client'

import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { KafkaProducerWrapper } from '../../kafka/producer'
import {
    Element,
    GroupTypeIndex,
    Hub,
    ISOTimestamp,
    Person,
    PersonMode,
    PreIngestionEvent,
    ProjectId,
    RawKafkaEvent,
    Team,
    TeamId,
    TimestampFormat,
} from '../../types'
import { DB, GroupId } from '../../utils/db/db'
import { elementsToString, extractElements } from '../../utils/db/elements-chain'
import { safeClickhouseString, sanitizeEventName, timeoutGuard } from '../../utils/db/utils'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { TeamManager } from '../../utils/team-manager'
import { castTimestampOrNow } from '../../utils/utils'
import { GroupTypeManager, MAX_GROUP_TYPES_PER_TEAM } from './group-type-manager'
import { addGroupProperties } from './groups'
import { GroupStoreForBatch } from './groups/group-store-for-batch.interface'

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
        processPerson: boolean,
        groupStoreForBatch: GroupStoreForBatch
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

            const team = await this.teamManager.getTeam(teamId)
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
                    processPerson,
                    groupStoreForBatch
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
        processPerson: boolean,
        groupStoreForBatch: GroupStoreForBatch
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
            properties = await addGroupProperties(team.id, team.project_id, properties, this.groupTypeManager)

            if (event === '$groupidentify') {
                await this.upsertGroup(team.id, team.project_id, properties, timestamp, groupStoreForBatch)
            }
        }

        return {
            eventUuid,
            event,
            distinctId,
            properties,
            timestamp: timestamp.toISO() as ISOTimestamp,
            teamId: team.id,
            projectId: team.project_id,
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

    createEvent(preIngestionEvent: PreIngestionEvent, person: Person, processPerson: boolean): RawKafkaEvent {
        const { eventUuid: uuid, event, teamId, projectId, distinctId, properties, timestamp } = preIngestionEvent

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

        const rawEvent: RawKafkaEvent = {
            uuid,
            event: safeClickhouseString(event),
            properties: JSON.stringify(properties ?? {}),
            timestamp: castTimestampOrNow(timestamp, TimestampFormat.ClickHouse),
            team_id: teamId,
            project_id: projectId,
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

    private async upsertGroup(
        teamId: TeamId,
        projectId: ProjectId,
        properties: Properties,
        timestamp: DateTime,
        groupStoreForBatch: GroupStoreForBatch
    ): Promise<void> {
        if (!properties['$group_type'] || !properties['$group_key']) {
            return
        }

        const { $group_type: groupType, $group_key: groupKey, $group_set: groupPropertiesToSet } = properties
        const groupTypeIndex = await this.groupTypeManager.fetchGroupTypeIndex(teamId, projectId, groupType)
        if (groupTypeIndex !== null) {
            await groupStoreForBatch.upsertGroup(
                teamId,
                projectId,
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
                    promises.push(this.groupTypeManager.fetchGroupTypeIndex(team.id, team.project_id, groupType))
                }
            }

            await Promise.all(promises)
        } finally {
            clearTimeout(timeout)
            updateEventNamesAndPropertiesMsSummary.observe(Date.now() - timer.valueOf())
        }
    }
}
