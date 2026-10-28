import { useActions } from 'kea'
import { useMemo } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { IntegrationType } from '~/types'

import { useIntegrationManagementRestriction } from './integrationPermissions'
import { getGrantedScopes } from './integrationScopes'
import { integrationAuthorizeUrl, reconnectReturnUrl } from './integrationsLogic'

export function IntegrationScopesWarning({
    integration,
    schema,
}: {
    integration: IntegrationType
    schema?: { requiredScopes?: string }
}): JSX.Element {
    const { reportIntegrationConnectClicked } = useActions(eventUsageLogic)
    const restrictedReason = useIntegrationManagementRestriction()
    const grantedScopes = useMemo(() => getGrantedScopes(integration), [integration.config, integration])
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
                    to: integrationAuthorizeUrl({
                        kind: integration.kind,
                        next: reconnectReturnUrl(window.location.pathname, window.location.search),
                    }),
                    onClick: () =>
                        reportIntegrationConnectClicked(integration.kind, integration.kind, 'missing_scopes_reconnect'),
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
