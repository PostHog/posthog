import { DateTime } from 'luxon'
import { Summary } from 'prom-client'

import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { ISOTimestamp, PreIngestionEvent, ProjectId, Team, TeamId } from '../../types'
import { sanitizeEventName, timeoutGuard } from '../../utils/db/utils'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from './group-type-manager'
import { addGroupProperties } from './groups'
import { GroupStoreForBatch } from './groups/group-store-for-batch.interface'

// for e.g. internal events we don't want to be available for users in the UI
const EVENTS_WITHOUT_EVENT_DEFINITION = ['$$plugin_metrics']

const processEventMsSummary = new Summary({
    name: 'process_event_ms',
    help: 'Duration spent in processEvent',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

const updateEventNamesAndPropertiesMsSummary = new Summary({
    name: 'update_event_names_and_properties_ms',
    help: 'Duration spent in updateEventNamesAndProperties',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export class EventsProcessor {
    constructor(
        private teamManager: TeamManager,
        private groupTypeManager: GroupTypeManager,
        private skipUpdateEventAndPropertiesStep: boolean
    ) {}

    public async processEvent(
        distinctId: string,
        data: PluginEvent,
        team: Team,
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

        if (this.skipUpdateEventAndPropertiesStep === false) {
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
