import api from 'lib/api'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { HogFunctionInputSchemaType, IntegrationType } from '~/types'

export function HubSpotScopesWarning({
    integration,
    schema,
}: {
    integration: IntegrationType
    schema?: HogFunctionInputSchemaType
}): JSX.Element {
    const requiredScopes = schema?.requiredScopes?.split(' ') || []
    const missingScopes = requiredScopes.filter((scope: string) => !integration.config.scopes?.includes(scope))

    if (missingScopes.length === 0 || integration.config.scopes === undefined) {
        return <></>
    }
    return (
        <div className="p-2">
            <LemonBanner
                type="error"
                action={{
                    children: 'Reconnect',
                    disableClientSideRouting: true,
                    to: api.integrations.authorizeUrl({
                        kind: integration.kind,
                        next: window.location.pathname,
                    }),
                }}
            >
                Required scopes are missing: [{missingScopes.join(', ')}]. Note that some features may not be available
                on your current HubSpot plan. Check out{' '}
                <Link to="https://developers.hubspot.com/beta-docs/guides/apps/authentication/scopes">this page</Link>{' '}
                for more details.
            </LemonBanner>
        </div>
    )
}
