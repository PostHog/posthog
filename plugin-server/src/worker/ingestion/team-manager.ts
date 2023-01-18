import { StatsD } from 'hot-shots'
import LRU from 'lru-cache'

import { ONE_MINUTE } from '../../config/constants'
import { Team, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'

export class TeamManager {
    db: DB
    teamCache: LRU<TeamId, Team | null>
    tokenToTeamIdCache: LRU<string, TeamId | null>
    statsd?: StatsD

    constructor(db: DB, statsd?: StatsD) {
        this.db = db
        this.statsd = statsd

        this.teamCache = new LRU({
            max: 10000,
            maxAge: 2 * ONE_MINUTE,
            // being explicit about the fact that we want to update
            // the team cache every 2min, irrespective of the last access
            updateAgeOnGet: false,
        })
        this.tokenToTeamIdCache = new LRU({
            // TODO: add `maxAge` to ensure we avoid negatively caching teamId as null.
            max: 100_000,
        })
    }

    public async fetchTeam(teamId: number): Promise<Team | null> {
        const cachedTeam = this.teamCache.get(teamId)
        if (cachedTeam !== undefined) {
            return cachedTeam
        }

        const timeout = timeoutGuard(`Still running "fetchTeam". Timeout warning after 30 sec!`)
        try {
            const team: Team | null = await this.db.fetchTeam(teamId)
            this.teamCache.set(teamId, team)
            return team
        } finally {
            clearTimeout(timeout)
        }
    }

    public async getTeamByToken(token: string): Promise<Team | null> {
        const cachedTeamId = this.tokenToTeamIdCache.get(token)

        // tokenToTeamIdCache.get returns `undefined` if the value doesn't
        // exist so we check for the value being `null` as that means we've
        // explictly cached that the team does not exist
        if (cachedTeamId === null) {
            return null
        } else if (cachedTeamId) {
            const cachedTeam = this.teamCache.get(cachedTeamId)
            if (cachedTeam) {
                return cachedTeam
            }
        }

        const timeout = timeoutGuard(`Still running "fetchTeam". Timeout warning after 30 sec!`)
        try {
            const team = await this.db.fetchTeamByToken(token)
            if (!team) {
                // explicitly cache a null to avoid
                // unnecessary lookups in the future
                this.tokenToTeamIdCache.set(token, null)
                return null
            }

            this.tokenToTeamIdCache.set(token, team.id)
            this.teamCache.set(team.id, team)
            return team
        } finally {
            clearTimeout(timeout)
        }
    }
}
