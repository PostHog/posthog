import api from 'lib/api'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { Link } from 'lib/lemon-ui/Link'

import { FieldScopes } from './fieldScopes'

/**
 * Sits under a field whose connection is missing the permission only that field needs. The value
 * still saves and still goes out, so this reads as a hint rather than an error.
 */
export function MissingScopesHint({ fieldScopes }: { fieldScopes: FieldScopes }): JSX.Element | null {
    if (!fieldScopes) {
        return null
    }

    const { integration, missingScopes } = fieldScopes
    const name = getIntegrationNameFromKind(integration.kind)

    return (
        <p className="mb-0 text-warning">
            Your {name} connection does not have the <code>{missingScopes.join(' ')}</code>{' '}
            {missingScopes.length === 1 ? 'permission' : 'permissions'}, so this field has no effect.{' '}
            <Link
                disableClientSideRouting
                to={api.integrations.authorizeUrl({ kind: integration.kind, next: window.location.pathname })}
            >
                Reconnect {name}
            </Link>{' '}
            to grant it.
        </p>
    )
}
