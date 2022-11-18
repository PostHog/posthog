import LRU from 'lru-cache'

import { RawOrganization, Team, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { TeamManager } from './team-manager'

const ONE_DAY = 24 * 60 * 60 * 1000

export class OrganizationManager {
    db: DB
    teamManager: TeamManager
    organizationCache: LRU<RawOrganization['id'], RawOrganization>
    availableFeaturesCache: LRU<TeamId, string[]>

    constructor(db: DB, teamManager: TeamManager) {
        this.db = db
        this.teamManager = teamManager
        this.organizationCache = new LRU({
            max: 10_000,
            // 30 seconds
            maxAge: 30_000,
            // being explicit about the fact that we want to update
            // the team cache every 2min, irrespective of the last access
            updateAgeOnGet: false,
        })
        this.availableFeaturesCache = new LRU({
            max: 10_000,
            maxAge: ONE_DAY,
            // being explicit about the fact that we want to update
            // the team cache every day, irrespective of the last access
            updateAgeOnGet: false,
        })
    }

    public async fetchOrganization(organizationId: RawOrganization['id']): Promise<RawOrganization | null> {
        const cachedOrganization = this.organizationCache.get(organizationId)
        if (cachedOrganization) {
            return cachedOrganization
        }

        const timeout = timeoutGuard(`Still running "fetchOrganization". Timeout warning after 30 sec!`)
        try {
            const organization: RawOrganization | null = (await this.db.fetchOrganization(organizationId)) || null
            if (organization) {
                this.organizationCache.set(organizationId, organization)
            }
            return organization
        } finally {
            clearTimeout(timeout)
        }
    }

    public async hasAvailableFeature(teamId: TeamId, feature: string, team?: Team): Promise<boolean> {
        const cachedAvailableFeatures = this.availableFeaturesCache.get(teamId)

        if (cachedAvailableFeatures !== undefined) {
            return cachedAvailableFeatures.includes(feature)
        }

        const _team = team || (await this.teamManager.fetchTeam(teamId))

        if (!_team) {
            return false
        }

        const organization = await this.fetchOrganization(_team.organization_id)
        const availableFeatures = organization?.available_features || []
        this.availableFeaturesCache.set(teamId, availableFeatures)

        return availableFeatures.includes(feature)
    }

    public resetAvailableFeatureCache(organizationId: string) {
        this.availableFeaturesCache.reset()
        this.organizationCache.del(organizationId)
    }
}
