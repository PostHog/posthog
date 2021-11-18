import { GroupTypeIndex, GroupTypeToColumnIndex, Team, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { posthog } from '../../utils/posthog'
import { getByAge } from '../../utils/utils'
import { TeamManager } from './team-manager'

export class GroupTypeManager {
    db: DB
    teamManager: TeamManager
    groupTypesCache: Map<number, [GroupTypeToColumnIndex, number]>
    instanceSiteUrl: string

    constructor(db: DB, teamManager: TeamManager, instanceSiteUrl?: string | null) {
        this.db = db
        this.teamManager = teamManager
        this.groupTypesCache = new Map()
        this.instanceSiteUrl = instanceSiteUrl || 'unknown'
    }

    public async fetchGroupTypes(teamId: TeamId): Promise<GroupTypeToColumnIndex> {
        const cachedGroupTypes = getByAge(this.groupTypesCache, teamId)
        if (cachedGroupTypes) {
            return cachedGroupTypes
        }

        const timeout = timeoutGuard(`Still running "fetchGroupTypes". Timeout warning after 30 sec!`)
        try {
            const teamGroupTypes: GroupTypeToColumnIndex = await this.db.fetchGroupTypes(teamId)
            this.groupTypesCache.set(teamId, [teamGroupTypes, Date.now()])
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
                this.groupTypesCache.delete(teamId)
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

        posthog.identify('plugin-server')
        posthog.capture('group type ingested', {
            team: team.uuid,
            groupType,
            groupTypeIndex,
            $groups: {
                project: team.uuid,
                organization: team.organization_id,
                instance: this.instanceSiteUrl,
            },
        })
    }
}
