import { useValues } from 'kea'

import { getMissingScopes } from 'lib/integrations/IntegrationScopesWarning'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { CyclotronJobInputSchemaType, IntegrationType } from '~/types'

import { CyclotronJobInputConfiguration } from '../types'

export type FieldScopes = { integration: IntegrationType; missingScopes: string[] } | null

/**
 * Scopes an input declares in `requiredScopes` that the connection it names in `integration_key`
 * hasn't granted. Scopes on the `integration` input itself are the connection's own hard
 * requirement and are handled by ``IntegrationScopesWarning``, so they are skipped here.
 *
 * Returns null for a connection with no recorded scopes — same fail-open behavior as that banner.
 */
export function useFieldMissingScopes(
    schema: CyclotronJobInputSchemaType,
    configuration?: CyclotronJobInputConfiguration,
    parentConfiguration?: CyclotronJobInputConfiguration
): FieldScopes {
    const { integrations } = useValues(integrationsLogic)

    const integrationKey = schema.integration_key
    if (schema.type === 'integration' || !schema.requiredScopes || !integrationKey) {
        return null
    }

    const inputs = { ...configuration?.inputs, ...parentConfiguration?.inputs }
    const integration = integrations?.find((i) => i.id === inputs[integrationKey]?.value)
    if (!integration) {
        return null
    }

    const missingScopes = getMissingScopes(integration, schema.requiredScopes.split(' '))
    return missingScopes.length ? { integration, missingScopes } : null
}
