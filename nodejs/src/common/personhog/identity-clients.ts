import { createClient } from '@connectrpc/connect'

import { PersonHogIdentity } from '~/common/generated/personhog/personhog/identity/v1/identity_pb'

import { PersonHogClientConfig, createPersonhogTransport } from './client'
import { PersonhogIdentityOperations } from './identity'

/**
 * Client for the identity server; a separate factory from
 * PersonHogClient because it answers on a different address than the
 * router.
 */
export function createIdentityClients(config: PersonHogClientConfig): {
    identity: PersonhogIdentityOperations
    close: () => void
} {
    const { transport, stateMonitor } = createPersonhogTransport(config)
    return {
        identity: new PersonhogIdentityOperations(createClient(PersonHogIdentity, transport)),
        close: () => stateMonitor.close(),
    }
}
