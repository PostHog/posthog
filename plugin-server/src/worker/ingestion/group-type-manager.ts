import LRU from 'lru-cache'

import { GroupTypeIndex, GroupTypeToColumnIndex, Team, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { posthog } from '../../utils/posthog'
import { TeamManager } from './team-manager'

export class GroupTypeManager {
    db: DB
    teamManager: TeamManager
    groupTypesCache: LRU<number, GroupTypeToColumnIndex>
    instanceSiteUrl: string

    constructor(db: DB, teamManager: TeamManager, instanceSiteUrl?: string | null) {
        this.db = db
        this.teamManager = teamManager
        this.groupTypesCache = new LRU({
            max: 10_000,
            // 30 seconds
            maxAge: 30_000,
            // being explicit about the fact that we want to update
            // the team cache every 2min, irrespective of the last access
            updateAgeOnGet: false,
        })
        this.instanceSiteUrl = instanceSiteUrl || 'unknown'
    }

    public async fetchGroupTypes(teamId: TeamId): Promise<GroupTypeToColumnIndex> {
        const cachedGroupTypes = this.groupTypesCache.get(teamId)
        if (cachedGroupTypes) {
            return cachedGroupTypes
        }

        const timeout = timeoutGuard(`Still running "fetchGroupTypes". Timeout warning after 30 sec!`)
        try {
            const teamGroupTypes: GroupTypeToColumnIndex = await this.db.fetchGroupTypes(teamId)
            this.groupTypesCache.set(teamId, teamGroupTypes)
            return teamGroupTypes
        } finally {
            clearTimeout(timeout)
        }
    }

    public async fetchGroupTypeIndex(teamId: TeamId, groupType: string): Promise<GroupTypeIndex | null> {
        const groupTypes = await this.fetchGroupTypes(teamId)

        if (groupType in groupTypes) {
            return groupTypes[groupType]
        } else {
            const [groupTypeIndex, isInsert] = await this.db.insertGroupType(
                teamId,
                groupType,
                Object.keys(groupTypes).length
            )
            if (groupTypeIndex !== null) {
                this.groupTypesCache.del(teamId)
            }

            if (isInsert && groupTypeIndex !== null) {
                await this.captureGroupTypeInsert(teamId, groupType, groupTypeIndex)
            }
            return groupTypeIndex
        }
    }

    private async captureGroupTypeInsert(teamId: TeamId, groupType: string, groupTypeIndex: GroupTypeIndex) {
        const team: Team | null = await this.teamManager.fetchTeam(teamId)

        if (!team) {
            return
        }

        posthog.capture({
            distinctId: 'plugin-server',
            event: 'group type ingested',
            properties: {
                team: team.uuid,
                groupType,
                groupTypeIndex,
            },
            groups: {
                project: team.uuid,
                organization: team.organization_id,
                instance: this.instanceSiteUrl,
            },
        })
    }
}
