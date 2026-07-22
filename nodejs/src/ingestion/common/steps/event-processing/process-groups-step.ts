import { DateTime } from 'luxon'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { sanitizeString } from '~/common/utils/db/utils'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { Properties } from '~/plugin-scaffold'
import { PreIngestionEvent, ProjectId, Team, TeamId } from '~/types'

import { EventPipelineRunnerOptions } from './event-pipeline-options'
import { addGroupProperties } from './groups'

const EVENTS_WITHOUT_EVENT_DEFINITION = ['$$plugin_metrics']

export interface ProcessGroupsStepInput {
    preparedEvent: PreIngestionEvent
    team: Team
    processPerson: boolean
    groupStoreForBatch: GroupStoreForBatch
}

export type ProcessGroupsStepResult<TInput> = TInput

export function createProcessGroupsStep<TInput extends ProcessGroupsStepInput>(
    teamManager: TeamManager,
    groupTypeManager: GroupTypeManager,
    options: Pick<EventPipelineRunnerOptions, 'SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP'>
): ProcessingStep<TInput, ProcessGroupsStepResult<TInput>> {
    return async function processGroupsStep(input: TInput) {
        const { preparedEvent, team, processPerson, groupStoreForBatch } = input

        if (!options.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP) {
            try {
                await updateGroupsAndFirstEvent(teamManager, groupTypeManager, team, preparedEvent)
            } catch (err) {
                captureException(err, { tags: { team_id: team.id } })
                logger.warn('⚠️', 'Failed to update groups and first event for event ', {
                    event: preparedEvent.event,
                    properties: preparedEvent.properties,
                    err,
                })
            }
        }

        if (processPerson) {
            preparedEvent.properties = await addGroupProperties(
                team.id,
                team.project_id,
                preparedEvent.properties,
                groupTypeManager,
                DateTime.fromISO(preparedEvent.timestamp)
            )

            if (preparedEvent.event === '$groupidentify') {
                const warnings = await upsertGroup(
                    groupTypeManager,
                    groupStoreForBatch,
                    team.id,
                    team.project_id,
                    preparedEvent,
                    DateTime.fromISO(preparedEvent.timestamp)
                )
                return ok(input, [], warnings)
            }
        }

        return ok(input)
    }
}

async function updateGroupsAndFirstEvent(
    teamManager: TeamManager,
    groupTypeManager: GroupTypeManager,
    team: Team,
    preparedEvent: PreIngestionEvent
): Promise<void> {
    if (EVENTS_WITHOUT_EVENT_DEFINITION.includes(preparedEvent.event)) {
        return
    }

    const promises: Promise<unknown>[] = [teamManager.setTeamIngestedEvent(team, preparedEvent.properties)]

    if (preparedEvent.event === '$groupidentify') {
        const { $group_type: groupType, $group_set: groupPropertiesToSet } = preparedEvent.properties
        if (groupType != null && groupPropertiesToSet != null) {
            promises.push(
                groupTypeManager.fetchGroupTypeIndex(
                    team.id,
                    team.project_id,
                    groupType,
                    DateTime.fromISO(preparedEvent.timestamp)
                )
            )
        }
    }

    await Promise.all(promises)
}

// Group properties must be a plain JSON object — anything else (string, number,
// array, ...) would reach Postgres as an invalid jsonb parameter and poison the
// whole write batch.
function isValidGroupSet(value: unknown): value is Properties {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function upsertGroup(
    groupTypeManager: GroupTypeManager,
    groupStore: GroupStoreForBatch,
    teamId: TeamId,
    projectId: ProjectId,
    preparedEvent: PreIngestionEvent,
    timestamp: DateTime
): Promise<PipelineWarning[]> {
    const properties = preparedEvent.properties
    if (!properties['$group_type'] || !properties['$group_key']) {
        return []
    }

    const { $group_type: groupType, $group_key: groupKey, $group_set: groupPropertiesToSet } = properties

    if (groupPropertiesToSet != null && !isValidGroupSet(groupPropertiesToSet)) {
        return [
            {
                type: 'invalid_group_set',
                details: {
                    eventUuid: preparedEvent.eventUuid,
                    distinctId: preparedEvent.distinctId,
                    groupType: String(groupType),
                    groupKey: sanitizeString(String(groupKey)),
                    receivedType: Array.isArray(groupPropertiesToSet) ? 'array' : typeof groupPropertiesToSet,
                },
                key: String(groupKey),
            },
        ]
    }

    const groupTypeIndex = await groupTypeManager.fetchGroupTypeIndex(teamId, projectId, groupType, timestamp)
    if (groupTypeIndex !== null) {
        await groupStore.upsertGroup(
            teamId,
            projectId,
            groupTypeIndex,
            sanitizeString(groupKey.toString()),
            groupPropertiesToSet || {},
            timestamp
        )
    }
    return []
}
