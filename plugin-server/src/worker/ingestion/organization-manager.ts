import { RawOrganization, Team, TeamId } from '../../types'
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
    availableFeaturesCache: Map<TeamId, [Array<string>, number]>

    constructor(postgres: PostgresRouter, teamManager: TeamManager) {
        this.postgres = postgres
        this.teamManager = teamManager
        this.organizationCache = new Map()
        this.availableFeaturesCache = new Map()
    }

    public async fetchOrganization(organizationId: RawOrganization['id']): Promise<RawOrganization | null> {
        const cachedOrganization = getByAge(this.organizationCache, organizationId)
        if (cachedOrganization) {
            return cachedOrganization
        }

        const timeout = timeoutGuard(`Still running "fetchOrganization". Timeout warning after 30 sec!`)
        try {
            const organization: RawOrganization | null =
                (await fetchOrganization(this.postgres, organizationId)) || null
            this.organizationCache.set(organizationId, [organization, Date.now()])
            return organization
        } finally {
            clearTimeout(timeout)
        }
    }

    public async hasAvailableFeature(teamId: TeamId, feature: string, team?: Team): Promise<boolean> {
        const cachedAvailableFeatures = getByAge(this.availableFeaturesCache, teamId, ONE_DAY)

        if (cachedAvailableFeatures !== undefined) {
            return cachedAvailableFeatures.includes(feature)
        }

        const _team = team || (await this.teamManager.fetchTeam(teamId))

        if (!_team) {
            return false
        }

        const organization = await this.fetchOrganization(_team.organization_id)
        const availableFeatures = organization?.available_features || []
        this.availableFeaturesCache.set(teamId, [availableFeatures, Date.now()])

        return availableFeatures.includes(feature)
    }

    public resetAvailableFeatureCache(organizationId: string) {
        this.availableFeaturesCache = new Map()
        this.organizationCache.delete(organizationId)
    }
}

export async function fetchOrganization(
    client: PostgresRouter,
    organizationId: string
): Promise<RawOrganization | undefined> {
    const selectResult = await client.query<RawOrganization>(
        PostgresUse.COMMON_READ,
        `SELECT * FROM posthog_organization WHERE id = $1`,
        [organizationId],
        'fetchOrganization'
    )
    return selectResult.rows[0]
}
