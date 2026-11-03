import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'

import { devLoginLogic } from '../devLoginLogic'

export function DevOAuthConnectionSection(): JSX.Element {
    const { devOAuthConnectors, devLoginOptionsLoading } = useValues(devLoginLogic)
    const { clearPendingOAuthConnection, startPendingOAuthConnection } = useActions(devLoginLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    if (pendingConnection) {
        return (
            <div>
                <p className="text-xs font-medium text-muted mb-1">Pending OAuth connection</p>
                <LemonButton
                    type="secondary"
                    size="small"
                    fullWidth
                    center
                    icon={<IconX />}
                    onClick={clearPendingOAuthConnection}
                    data-attr="dev-clear-pending-oauth-connection"
                    tooltip="Deletes the ph_pending_oauth_connection cookie, so these screens stop showing the app. The next= link in the URL still goes to the consent page after login."
                >
                    Clear {pendingConnection.clientName}
                </LemonButton>
            </div>
        )
    }
    return (
        <div>
            <p className="text-xs font-medium text-muted mb-1">Start an OAuth connection</p>
            {devOAuthConnectors.length > 0 ? (
                <div className="grid grid-cols-2 gap-1">
                    {devOAuthConnectors.map((connector) => (
                        <LemonButton
                            key={connector.client_id}
                            type="secondary"
                            size="small"
                            fullWidth
                            center
                            icon={
                                connector.logo_uri ? (
                                    <img src={connector.logo_uri} alt="" className="w-4 h-4 object-contain" />
                                ) : undefined
                            }
                            onClick={() => startPendingOAuthConnection(connector)}
                            data-attr={`dev-start-oauth-connection-${connector.client_id}`}
                            tooltip="Sets the ph_pending_oauth_connection cookie and a next= link to the consent page, as a connector would."
                        >
                            <span className="truncate">{connector.client_name}</span>
                        </LemonButton>
                    ))}
                </div>
            ) : (
                !devLoginOptionsLoading && (
                    <p className="text-xs text-muted m-0">Run generate_demo_data to add connector apps.</p>
                )
            )}
        </div>
    )
}
