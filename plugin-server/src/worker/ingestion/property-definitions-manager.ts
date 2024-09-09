import { Properties } from '@posthog/plugin-scaffold'
import { Summary } from 'prom-client'

import { Team } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { GroupTypeManager } from './group-type-manager'
import { TeamManager } from './team-manager'

// for e.g. internal events we don't want to be available for users in the UI
const EVENTS_WITHOUT_EVENT_DEFINITION = ['$$plugin_metrics']

const updateEventNamesAndPropertiesMsSummary = new Summary({
    name: 'update_event_names_and_properties_ms',
    help: 'Duration spent in updateEventNamesAndProperties',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export class GroupAndFirstEventManager {
    db: DB
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager

    constructor(teamManager: TeamManager, groupTypeManager: GroupTypeManager, db: DB) {
        this.db = db
        this.teamManager = teamManager
        this.groupTypeManager = groupTypeManager
    }

    public async updateGroupsAndFirstEvent(teamId: number, event: string, properties: Properties): Promise<void> {
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
            const team: Team | null = this.teamManager.getTeam(teamId)

            if (!team) {
                return
            }

            // We always track 1st event ingestion
            const promises = [this.teamManager.setTeamIngestedEvent(team, properties)]

            // We always insert/update group-types, so if this is a group-identify event, we hit
            // the group-type manager, making it insert or update as necessary.
            if (event === '$groupidentify') {
                const { $group_type: groupType, $group_set: groupPropertiesToSet } = properties
                if (groupType != null && groupPropertiesToSet != null) {
                    // This "fetch" is side-effecty, it inserts a group-type and assigns an index if one isn't found
                    const groupPromise = this.groupTypeManager.fetchGroupTypeIndex(teamId, groupType).then(() => {})
                    promises.push(groupPromise)
                }
            }

            await Promise.all(promises)
        } finally {
            clearTimeout(timeout)
            updateEventNamesAndPropertiesMsSummary.observe(Date.now() - timer.valueOf())
        }
    }
}
