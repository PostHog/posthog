import { DB, GroupId, GroupsData } from '../../utils/db/db'

export class LazyGroupsContainer {
    teamId: number
    groupIds: GroupId[]

    loaded: boolean

    private db: DB
    private promise: Promise<GroupsData> | null

    constructor(teamId: number, groupIds: GroupId[], db: DB) {
        this.teamId = teamId
        this.groupIds = groupIds
        this.db = db

        this.promise = null
        this.loaded = false
    }

    async get(): Promise<GroupsData> {
        if (!this.promise) {
            this.promise = this.db.getGroupsData(this.teamId, this.groupIds).then((groupsData) => {
                if (groupsData) {
                    this.loaded = true
                }
                return groupsData
            })
        }
        return this.promise
    }
}
