import type { CdpCoreServicesDeps } from './cdp-services'
import type { CdpConfig } from './config'
import { FrequencyCapValkeyConfig, createFrequencyCapValkeyPool } from './services/messaging/frequency-cap-valkey-pool'
import {
    RateLimiterValkeyConfig,
    createSesRateLimiterValkeyPool,
} from './services/rate-limiter/rate-limiter-valkey-pool'

type SandboxEmailCapValkeyConfig = RateLimiterValkeyConfig & Pick<CdpConfig, 'WORKFLOWS_SANDBOX_SENDER_ENABLED'>

export type EmailActionValkeys = Pick<
    CdpCoreServicesDeps,
    'emailValidationValkey' | 'frequencyCapValkey' | 'sandboxEmailCapValkey'
>

export function createEmailActionValkeys(
    config: SandboxEmailCapValkeyConfig & FrequencyCapValkeyConfig
): EmailActionValkeys {
    return {
        emailValidationValkey: createSesRateLimiterValkeyPool(config, 'email-mx-validation'),
        frequencyCapValkey: createFrequencyCapValkeyPool(config),
        ...createSandboxEmailCapValkey(config),
    }
}

export function createSandboxEmailCapValkey(
    config: SandboxEmailCapValkeyConfig
): Pick<CdpCoreServicesDeps, 'sandboxEmailCapValkey'> {
    return config.WORKFLOWS_SANDBOX_SENDER_ENABLED
        ? {
              sandboxEmailCapValkey: createSesRateLimiterValkeyPool(config, 'sandbox-email-cap', {
                  optional: true,
                  failFast: true,
              }),
          }
        : {}
}
