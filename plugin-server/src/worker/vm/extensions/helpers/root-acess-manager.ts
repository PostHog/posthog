import { DB } from '../../../../utils/db/db'
import { TeamId } from './../../../../types'

const CACHE_TTL = 60 * 60 * 1000 // 1 hour

export class RootAccessManager {
    db: DB
    rootAcessTeamsCache: TeamId[]
    rootAccessTeamsCacheExpiration: number

    constructor(db: DB) {
        this.db = db
        this.rootAcessTeamsCache = []
        this.rootAccessTeamsCacheExpiration = 0
    }

    public async getRootAccessTeams(): Promise<TeamId[]> {
        if (Date.now() > this.rootAccessTeamsCacheExpiration) {
            this.rootAcessTeamsCache = (await this.db.getTeamsInOrganizationsWithRootPluginAccess()).map(
                (team) => team.id
            )
            this.rootAccessTeamsCacheExpiration = Date.now() + CACHE_TTL
        }

        return this.rootAcessTeamsCache
    }
}
