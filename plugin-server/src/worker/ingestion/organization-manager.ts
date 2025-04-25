import { Counter } from 'prom-client'

import { defaultConfig } from '../../config/config'
import { ProductFeature, RawOrganization, Team, TeamId } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { timeoutGuard } from '../../utils/db/utils'
import { logger } from '../../utils/logger'
import { TeamManagerLazy } from '../../utils/team-manager-lazy'
import { getByAge } from '../../utils/utils'
import { TeamManager } from './team-manager'

const ONE_DAY = 24 * 60 * 60 * 1000

const availableFeatureComparisonCounter = new Counter({
    name: 'available_feature_comparison',
    help: 'Checks available feature returned is the same as the lazy available feature',
    labelNames: ['result'],
})

type OrganizationCache<T> = Map<RawOrganization['id'], [T, number]>

export class OrganizationManager {
    postgres: PostgresRouter
    teamManager: TeamManager
    organizationCache: OrganizationCache<RawOrganization | null>
    availableProductFeaturesCache: Map<TeamId, [Array<ProductFeature>, number]>

    constructor(postgres: PostgresRouter, teamManager: TeamManager, private teamManagerLazy?: TeamManagerLazy) {
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
            const organization: RawOrganization | null =
                (await fetchOrganization(this.postgres, organizationId)) || null
            this.organizationCache.set(organizationId, [organization, Date.now()])
            return organization
        } finally {
            clearTimeout(timeout)
        }
    }

    public async hasAvailableFeature(teamId: TeamId, feature: string, team?: Team): Promise<boolean> {
        if (defaultConfig.USE_LAZY_TEAM_MANAGER && this.teamManagerLazy) {
            return await this.teamManagerLazy.hasAvailableFeature(teamId, feature)
        }

        const result = await this._hasAvailableFeature(teamId, feature, team)

        try {
            // NOTE: This is testing code to compare the outputs and ensure all is valid
            if (defaultConfig.LAZY_TEAM_MANAGER_COMPARISON && this.teamManagerLazy) {
                const lazyResult = await this.teamManagerLazy.hasAvailableFeature(teamId, feature)

                if (lazyResult === result) {
                    availableFeatureComparisonCounter.inc({ result: 'equal' })
                } else {
                    availableFeatureComparisonCounter.inc({ result: 'not_equal' })
                }
            }
        } catch (e) {
            logger.error('Error comparing available features', { error: e })
        }
        return result
    }

    private async _hasAvailableFeature(teamId: TeamId, feature: string, team?: Team): Promise<boolean> {
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

        if (defaultConfig.LAZY_TEAM_MANAGER_COMPARISON && this.teamManagerLazy) {
            this.teamManagerLazy.orgAvailableFeaturesChanged(organizationId)
        }
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
