import { PluginEvent } from '~/plugin-scaffold'
import { Team } from '~/types'
import { GroupTypeManager } from '~/worker/ingestion/group-type-manager'

import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface GroupTypeMappingInput {
    event: PluginEvent
    team: Team
}

/**
 * Creates a step that maps group types to their indexes.
 * Wraps the existing GroupTypeManager as a pipeline step.
 *
 * Adds $group_<index> properties to event.properties for each group
 * specified in $groups.
 */
export function createGroupTypeMappingStep<T extends GroupTypeMappingInput>(
    groupTypeManager: GroupTypeManager
): ProcessingStep<T, T> {
    return async function groupTypeMappingStep(input) {
        const { event, team } = input

        // Extract group identifiers from properties
        const groups = event.properties?.$groups as Record<string, string> | undefined

        // If no groups, pass through without mapping
        if (!groups || !team.project_id) {
            return ok(input)
        }

        // Resolve group type indexes and add $group_<index> properties
        const groupProperties: Record<string, string> = {}
        for (const [groupType, groupKey] of Object.entries(groups)) {
            const index = await groupTypeManager.fetchGroupTypeIndex(team.id, team.project_id, groupType)
            if (index !== null) {
                groupProperties[`$group_${index}`] = groupKey
            }
        }

        if (Object.keys(groupProperties).length === 0) {
            return ok(input)
        }

        const enrichedEvent: PluginEvent = {
            ...event,
            properties: {
                ...event.properties,
                ...groupProperties,
            },
        }

        return ok({ ...input, event: enrichedEvent })
    }
}
