import { useMemo } from 'react'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { IntegrationType } from '~/types'

/**
 * Extract the granted OAuth scopes from an integration's stored config. Tolerates the
 * various shapes different providers persist: ``config.scope`` vs ``config.scopes``,
 * space- or comma-separated strings, or a pre-split array. Returns an empty array when
 * no recognizable scope list is present (e.g. legacy rows predating the field).
 *
 * Exported so any caller that needs to decide "is this install missing a scope" (the
 * banner below, the OAuth landing-page status hook, etc.) reaches the same verdict.
 */
export function getGrantedScopes(integration: IntegrationType): string[] {
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
    return scopes.filter((scope: any) => typeof scope === 'object').reduce((a, b) => (a.length > b.length ? a : b), [])
}

/** Scopes from ``schema.requiredScopes`` that the integration hasn't granted. */
export function getMissingScopes(integration: IntegrationType, requiredScopes: string[]): string[] {
    const granted = getGrantedScopes(integration)
    if (granted.length === 0) {
        return []
    }
    return requiredScopes.filter((scope) => !granted.includes(scope))
}

export function IntegrationScopesWarning({
    integration,
    schema,
}: {
    integration: IntegrationType
    schema?: { requiredScopes?: string }
}): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const grantedScopes = useMemo(() => getGrantedScopes(integration), [integration.config])
    const requiredScopes = schema?.requiredScopes?.split(' ') || []
    const missingScopes = requiredScopes.filter((scope) => !grantedScopes.includes(scope))

    if (missingScopes.length === 0 || grantedScopes.length === 0) {
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
                    disabledReason: restrictedReason,
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
