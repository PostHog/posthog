import { useValues } from 'kea'

import { OAuthConnectionLogos } from 'lib/components/OAuthConnectionLogos/OAuthConnectionLogos'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'

import { oauthDeviceAuthorizeLogic } from '../oauthDeviceAuthorizeLogic'

export function DeviceDecision({ approved }: { approved: boolean }): JSX.Element {
    const { deviceGrant } = useValues(oauthDeviceAuthorizeLogic)

    return (
        <AuthScene notes={approved ? AUTH_NOTES.oauthDevice.approved : AUTH_NOTES.oauthDevice.denied}>
            <AuthSceneCard
                top={
                    deviceGrant ? (
                        <OAuthConnectionLogos appName={deviceGrant.client_name} logoUri={deviceGrant.logo_uri} />
                    ) : undefined
                }
            >
                <AuthCardTitle
                    className="mb-0"
                    title={approved ? 'Login approved' : 'Login denied'}
                    sub={
                        approved
                            ? 'Go back to your terminal to continue. You can close this window.'
                            : 'You can close this window and go back to your terminal.'
                    }
                />
            </AuthSceneCard>
        </AuthScene>
    )
}
