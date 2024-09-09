import { ProductFeature, RawOrganization, Team, TeamId } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { timeoutGuard } from '../../utils/db/utils'
import { getByAge } from '../../utils/utils'
import { TeamManager } from './team-manager'

const ONE_DAY = 24 * 60 * 60 * 1000

type OrganizationCache<T> = Map<RawOrganization['id'], [T, number]>

export class OrganizationManager {
    postgres: PostgresRouter
    teamManager: TeamManager
    organizationCache: OrganizationCache<RawOrganization | null>
    availableProductFeaturesCache: Map<TeamId, [Array<ProductFeature>, number]>

    constructor(postgres: PostgresRouter, teamManager: TeamManager) {
        this.postgres = postgres
        this.teamManager = teamManager
        this.organizationCache = new Map()
        this.availableProductFeaturesCache = new Map()
    }

    public async fetchOrganization(organizationId: RawOrganization['id']): Promise<RawOrganization | null> {
        const cachedOrganization = getByAge(this.organizationCache, organizationId)
        if (cachedOrganization) {
            return cachedOrganization
        }

        const timeout = timeoutGuard(`Still running "fetchOrganization". Timeout warning after 30 sec!`)
        try {
            const selectResult = await this.postgres.query<RawOrganization>(
                PostgresUse.COMMON_READ,
                `SELECT * FROM posthog_organization WHERE id = $1`,
                [organizationId],
                'fetchOrganization'
            )
            const organization: RawOrganization | null = selectResult.rows[0]
            this.organizationCache.set(organizationId, [organization, Date.now()])
            return organization
        } finally {
            clearTimeout(timeout)
        }
    }

    public async hasAvailableFeature(teamId: TeamId, feature: string, team?: Team): Promise<boolean> {
        const cachedAvailableFeatures = getByAge(this.availableProductFeaturesCache, teamId, ONE_DAY)

        if (cachedAvailableFeatures !== undefined) {
            const availableProductFeaturesKeys = cachedAvailableFeatures.map((feature) => feature.key)
            return availableProductFeaturesKeys.includes(feature)
        }

        const _team = team || (await this.teamManager.fetchTeam(teamId))

        if (!_team) {
            return false
        }

        const organization = await this.fetchOrganization(_team.organization_id)
        const availableProductFeatures = organization?.available_product_features || []
        this.availableProductFeaturesCache.set(teamId, [availableProductFeatures, Date.now()])

        const availableProductFeaturesKeys = availableProductFeatures.map((feature) => feature.key)
        return availableProductFeaturesKeys.includes(feature)
    }

    public resetAvailableProductFeaturesCache(organizationId: string) {
        this.availableProductFeaturesCache = new Map()
        this.organizationCache.delete(organizationId)
    }
}
