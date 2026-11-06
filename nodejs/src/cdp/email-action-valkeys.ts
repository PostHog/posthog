import type { CdpCoreServicesDeps } from './cdp-services'
import type { CdpConfig } from './config'
import {
    RateLimiterValkeyConfig,
    createSesRateLimiterValkeyPool,
} from './services/rate-limiter/rate-limiter-valkey-pool'

type SandboxEmailCapValkeyConfig = RateLimiterValkeyConfig & Pick<CdpConfig, 'WORKFLOWS_SANDBOX_SENDER_ENABLED'>

export function createSandboxEmailCapValkey(
    config: SandboxEmailCapValkeyConfig
): Pick<CdpCoreServicesDeps, 'sandboxEmailCapValkey'> {
    return {
        sandboxEmailCapValkey: config.WORKFLOWS_SANDBOX_SENDER_ENABLED
            ? createSesRateLimiterValkeyPool(config, 'sandbox-email-cap', { mode: 'failFast' })
            : null,
    }
}
