import api from 'lib/api'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { Link } from 'lib/lemon-ui/Link'

import { CyclotronJobInputSchemaType } from '~/types'

import { CyclotronJobInputConfiguration } from '../types'
import { useFieldMissingScopes } from './fieldScopes'

/**
 * Sits under a field whose connection is missing a permission only that field needs. What a missing
 * permission costs differs per field — an unusable picker, a value the destination drops — so this
 * states the permission and the way to grant it, and leaves the consequence to the field itself.
 *
 * Render it only where ``declaresFieldScopes`` holds: it subscribes to every integration on the team.
 */
export function MissingScopesHint({
    schema,
    configuration,
    parentConfiguration,
}: {
    schema: CyclotronJobInputSchemaType
    configuration?: CyclotronJobInputConfiguration
    parentConfiguration?: CyclotronJobInputConfiguration
}): JSX.Element | null {
    const fieldScopes = useFieldMissingScopes(schema, configuration, parentConfiguration)
    if (!fieldScopes) {
        return null
    }

    const { integration, missingScopes } = fieldScopes
    const name = getIntegrationNameFromKind(integration.kind)

    return (
        <p className="mb-0 text-warning">
            This field needs the <code>{missingScopes.join(' ')}</code>{' '}
            {missingScopes.length === 1 ? 'permission' : 'permissions'}, which your {name} connection does not have.{' '}
            <Link
                disableClientSideRouting
                to={api.integrations.authorizeUrl({ kind: integration.kind, next: window.location.pathname })}
            >
                Reconnect {name}
            </Link>{' '}
            to grant {missingScopes.length === 1 ? 'it' : 'them'}.
        </p>
    )
}
