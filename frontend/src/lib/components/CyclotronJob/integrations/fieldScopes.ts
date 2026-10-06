import { useValues } from 'kea'

import { getMissingScopes } from 'lib/integrations/IntegrationScopesWarning'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { CyclotronJobInputSchemaType, IntegrationType } from '~/types'

import { CyclotronJobInputConfiguration } from '../types'

export type FieldScopes = { integration: IntegrationType; missingScopes: string[] } | null

/**
 * Whether an input asks for scopes of its own, rather than for the connection as a whole. Scopes on
 * the `integration` input are that connection's hard requirement, handled by
 * ``IntegrationScopesWarning``.
 *
 * A plain check, not a hook, so a form whose inputs declare no scopes never mounts
 * ``integrationsLogic`` and never loads the team's integrations.
 */
export function declaresFieldScopes(schema: CyclotronJobInputSchemaType): boolean {
    return schema.type !== 'integration' && !!schema.requiredScopes && !!schema.integration_key
}

/**
 * Scopes an input declares in `requiredScopes` that the connection it names in `integration_key`
 * hasn't granted. Returns null for a connection with no recorded scopes — same fail-open behavior as
 * the connection-level banner.
 */
export function useFieldMissingScopes(
    schema: CyclotronJobInputSchemaType,
    configuration?: CyclotronJobInputConfiguration,
    parentConfiguration?: CyclotronJobInputConfiguration
): FieldScopes {
    const { integrations } = useValues(integrationsLogic)

    if (!declaresFieldScopes(schema)) {
        return null
    }

    const inputs = { ...configuration?.inputs, ...parentConfiguration?.inputs }
    const integration = integrations?.find((i) => i.id === inputs[schema.integration_key as string]?.value)
    if (!integration) {
        return null
    }

    const missingScopes = getMissingScopes(integration, (schema.requiredScopes as string).split(' '))
    return missingScopes.length ? { integration, missingScopes } : null
}
