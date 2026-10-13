import { createClient } from '@connectrpc/connect'

import { PersonHogIdentity } from '~/common/generated/personhog/personhog/identity/v1/identity_pb'

import { PersonHogClientConfig, createPersonhogTransport } from './client'
import { PersonhogIdentityOperations } from './identity'

/**
 * Client for the identity server; a separate factory from
 * PersonHogClient because it answers on a different address than the
 * router.
 */
export function createIdentityClients(
    config: PersonHogClientConfig,
    options: { mergeTimeoutMs?: number } = {}
): {
    identity: PersonhogIdentityOperations
    close: () => void
} {
    // A zero or negative deadline would kill every merge client-side.
    if (
        options.mergeTimeoutMs !== undefined &&
        (!Number.isInteger(options.mergeTimeoutMs) || options.mergeTimeoutMs < 1)
    ) {
        throw new Error(`PERSONHOG_MERGE_TIMEOUT_MS must be an integer >= 1, got ${options.mergeTimeoutMs}`)
    }
    const { transport, stateMonitor } = createPersonhogTransport(config)
    return {
        identity: new PersonhogIdentityOperations(createClient(PersonHogIdentity, transport), options),
        close: () => stateMonitor.close(),
    }
}
