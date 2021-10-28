import { GroupTypeToColumnIndex, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { getByAge } from '../../utils/utils'

export class GroupTypeManager {
    db: DB
    groupTypesCache: Map<number, [GroupTypeToColumnIndex, number]>

    constructor(db: DB) {
        this.db = db
        this.groupTypesCache = new Map()
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

    public async fetchGroupTypeIndex(teamId: TeamId, groupType: string): Promise<number | null> {
        const groupTypes = await this.fetchGroupTypes(teamId)

        if (groupType in groupTypes) {
            return groupTypes[groupType]
        } else {
            const response = await this.db.insertGroupType(teamId, groupType, Object.keys(groupTypes).length)
            if (response !== null) {
                this.groupTypesCache.delete(teamId)
            }
            return response
        }
    }
}
