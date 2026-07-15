import { IntegrationType } from '~/cdp/types'
import { JWT, PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { buildIntegerMatcherWithPercentage } from '~/common/config/config'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'
import { ValueMatcher } from '~/types'

export type IntegrationGatewayConfig = {
    CDP_INTEGRATION_GATEWAY_URL: string
    CDP_INTEGRATION_GATEWAY_JWT_SECRET: string
    // Team-ids + percentage rollout string, e.g. '' (off), '*', '123,456', '*:0.05', '123,*:0.05'.
    CDP_INTEGRATION_GATEWAY_ROLLOUT: string
}

// Tokens are minted per request and only need to outlive one call; keep them short.
const TOKEN_TTL_SECONDS = 60

type FetchResponseBody = {
    integrations: Record<string, IntegrationType | null>
}

/**
 * Client for the Rust integration-gateway credential service. Mints a per-team scoped JWT and
 * fetches decrypted integrations over HTTP. The gateway enforces team-scope itself (a wrong-team id
 * comes back null), so this is a drop-in for the in-process SQL+decrypt path.
 *
 * Callers gate on `enabledForTeam` and fall back to Postgres on any error — see IntegrationManagerService.
 */
export class IntegrationGatewayService {
    private jwt: JWT
    private rolloutMatcher: ValueMatcher<number>
    private baseUrl: string

    constructor(config: IntegrationGatewayConfig) {
        this.baseUrl = config.CDP_INTEGRATION_GATEWAY_URL.replace(/\/$/, '')
        this.jwt = new JWT(config.CDP_INTEGRATION_GATEWAY_JWT_SECRET)
        this.rolloutMatcher = buildIntegerMatcherWithPercentage(config.CDP_INTEGRATION_GATEWAY_ROLLOUT)
    }

    public enabledForTeam(teamId: number): boolean {
        return this.rolloutMatcher(teamId)
    }

    /**
     * Fetch decrypted integrations for one team. Returns a record keyed by stringified id; ids that
     * don't exist or belong to another team are `null`. Throws on transport/non-200 so the caller can
     * fall back to Postgres.
     */
    public async fetchMany(
        ids: IntegrationType['id'][],
        teamId: number
    ): Promise<Record<string, IntegrationType | null>> {
        const token = this.jwt.sign({ team_id: teamId, caller: 'cdp' }, PosthogJwtAudience.INTEGRATION_GATEWAY, {
            expiresIn: TOKEN_TTL_SECONDS,
        })

        const response = await internalFetch(`${this.baseUrl}/api/v1/credentials/fetch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ integration_ids: ids }),
        })

        if (response.status !== 200) {
            await response.dump()
            throw new Error(`integration-gateway returned ${response.status}`)
        }

        const body = (await response.json()) as FetchResponseBody
        const integrations = body.integrations ?? {}

        // Normalize: every requested id is present in the result, resolved or null.
        const out: Record<string, IntegrationType | null> = {}
        for (const id of ids) {
            out[id.toString()] = integrations[id.toString()] ?? null
        }
        return out
    }
}

/**
 * Build the gateway client from config, or return null when it isn't configured (no URL/secret) or
 * has an empty rollout — in which case consumers use the in-process Postgres path unchanged.
 */
export function createIntegrationGatewayService(config: IntegrationGatewayConfig): IntegrationGatewayService | null {
    if (!config.CDP_INTEGRATION_GATEWAY_URL || !config.CDP_INTEGRATION_GATEWAY_JWT_SECRET) {
        return null
    }
    if (!config.CDP_INTEGRATION_GATEWAY_ROLLOUT) {
        return null
    }
    logger.info('🔌', `Integration gateway enabled with rollout: ${config.CDP_INTEGRATION_GATEWAY_ROLLOUT}`)
    return new IntegrationGatewayService(config)
}
