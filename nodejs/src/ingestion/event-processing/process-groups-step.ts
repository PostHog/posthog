import { DateTime } from 'luxon'

import { Properties } from '~/plugin-scaffold'

import { PreIngestionEvent, ProjectId, Team, TeamId } from '../../types'
import { sanitizeString } from '../../utils/db/utils'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
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
                await upsertGroup(
                    groupTypeManager,
                    groupStoreForBatch,
                    team.id,
                    team.project_id,
                    preparedEvent.properties,
                    DateTime.fromISO(preparedEvent.timestamp)
                )
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

async function upsertGroup(
    groupTypeManager: GroupTypeManager,
    groupStore: GroupStoreForBatch,
    teamId: TeamId,
    projectId: ProjectId,
    properties: Properties,
    timestamp: DateTime
): Promise<void> {
    if (!properties['$group_type'] || !properties['$group_key']) {
        return
    }

    const { $group_type: groupType, $group_key: groupKey, $group_set: groupPropertiesToSet } = properties
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
}
