import { useMemo } from 'react'

import api from 'lib/api'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { CyclotronJobInputSchemaType, IntegrationType } from '~/types'

export function IntegrationScopesWarning({
    integration,
    schema,
}: {
    integration: IntegrationType
    schema?: CyclotronJobInputSchemaType
}): JSX.Element {
    const getScopes = useMemo((): string[] => {
        const scopes: any[] = []
        const possibleScopeLocation = [integration.config.scope, integration.config.scopes]

        possibleScopeLocation.map((scope) => {
            if (typeof scope === 'string') {
                scopes.push(scope.split(' '))
                scopes.push(scope.split(','))
            }
            if (typeof scope === 'object') {
                scopes.push(scope)
            }
        })
        return scopes
            .filter((scope: any) => typeof scope === 'object')
            .reduce((a, b) => (a.length > b.length ? a : b), [])
    }, [integration.config])

    const requiredScopes = schema?.requiredScopes?.split(' ') || []
    const missingScopes = requiredScopes.filter((scope: string) => !getScopes.includes(scope))

    if (missingScopes.length === 0 || getScopes.length === 0) {
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
                <span>Required scopes are missing: [{missingScopes.join(', ')}].</span>
                {integration.kind === 'hubspot' ? (
                    <span>
                        Note that some features may not be available on your current HubSpot plan. Check out{' '}
                        <Link to="https://developers.hubspot.com/beta-docs/guides/apps/authentication/scopes">
                            this page
                        </Link>{' '}
                        for more details.
                    </span>
                ) : null}
            </LemonBanner>
        </div>
    )
}
