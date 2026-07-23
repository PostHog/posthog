import { IntegrationType } from '~/cdp/types'
import { buildIntegerMatcherWithPercentage } from '~/common/config/config'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'
import { ValueMatcher } from '~/types'

export interface IntegrationGatewayServiceConfig {
    CDP_INTEGRATION_GATEWAY_URL: string
    CDP_INTEGRATION_GATEWAY_ROLLOUT: string
    CDP_INTEGRATION_GATEWAY_TIMEOUT_MS: number
}

// Self-reported caller label recorded in the gateway's audit trail.
const CALLER = 'cdp'

/**
 * Client for the integration gateway service. Reads decrypted credentials over
 * `POST /api/v1/credentials/fetch`, passing the team and caller in the request body — there is no
 * auth secret; access is bounded by the gateway's Cilium NetworkPolicy. Gated per team via a
 * rollout matcher; the caller (IntegrationManagerService) falls back to Postgres when this is
 * disabled or errors.
 */
export class IntegrationGatewayService {
    private baseUrl: string
    private rollout: ValueMatcher<number>
    private timeoutMs: number

    constructor(config: IntegrationGatewayServiceConfig) {
        this.baseUrl = config.CDP_INTEGRATION_GATEWAY_URL.replace(/\/+$/, '')
        this.rollout = buildIntegerMatcherWithPercentage(config.CDP_INTEGRATION_GATEWAY_ROLLOUT)
        this.timeoutMs = config.CDP_INTEGRATION_GATEWAY_TIMEOUT_MS
    }

    enabledForTeam(teamId: number): boolean {
        return this.rollout(teamId)
    }

    /**
     * Fetch decrypted integrations for a single team. Throws on any non-200 so the manager falls
     * back to Postgres. Every requested id is present in the result, resolved or null.
     */
    async fetchMany(ids: number[], teamId: number): Promise<Record<string, IntegrationType | null>> {
        const response = await internalFetch(`${this.baseUrl}/api/v1/credentials/fetch`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ team_id: teamId, caller: CALLER, integration_ids: ids }),
            // Fast-fail so a slow/degraded gateway falls back to Postgres quickly instead of every
            // hot-path read blocking on the long default external-request timeout.
            timeoutMs: this.timeoutMs,
        })

        if (response.status !== 200) {
            await response.dump()
            throw new Error(`integration gateway returned ${response.status}`)
        }

        const body = (await response.json()) as { integrations?: Record<string, IntegrationType | null> }
        // A 200 with a malformed body must trigger the Postgres fallback, not silently resolve every
        // id to null (which would surface as "integration not found" for real, connected integrations).
        if (!body || typeof body.integrations !== 'object' || body.integrations === null) {
            throw new Error('integration gateway returned a malformed response')
        }
        const gatewayResult = body.integrations

        const result: Record<string, IntegrationType | null> = {}
        for (const id of ids) {
            result[id] = gatewayResult[String(id)] ?? null
        }
        return result
    }
}

/**
 * Build the gateway client, or null when it isn't fully configured. Requiring both settings
 * (url + non-empty rollout) keeps the feature dark by default.
 */
export function createIntegrationGatewayService(
    config: IntegrationGatewayServiceConfig
): IntegrationGatewayService | null {
    const missing = [
        !config.CDP_INTEGRATION_GATEWAY_URL && 'CDP_INTEGRATION_GATEWAY_URL',
        !config.CDP_INTEGRATION_GATEWAY_ROLLOUT && 'CDP_INTEGRATION_GATEWAY_ROLLOUT',
    ].filter(Boolean)
    if (missing.length > 0) {
        // One-time startup breadcrumb: makes it obvious why credential reads stay on Postgres.
        logger.info('[IntegrationManager]', 'Integration gateway disabled; reading credentials from Postgres', {
            missing,
        })
        return null
    }
    logger.info('[IntegrationManager]', 'Integration gateway enabled for credential reads', {
        url: config.CDP_INTEGRATION_GATEWAY_URL,
        rollout: config.CDP_INTEGRATION_GATEWAY_ROLLOUT,
    })
    return new IntegrationGatewayService(config)
}
