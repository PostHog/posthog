import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { OAuthConnectionLogos } from 'lib/components/OAuthConnectionLogos/OAuthConnectionLogos'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'

import { oauthDeviceAuthorizeLogic } from '../oauthDeviceAuthorizeLogic'

export function DeviceCodeForm(): JSX.Element {
    const { userCode, deviceGrantLoading, error, goingToLogin } = useValues(oauthDeviceAuthorizeLogic)
    const { setUserCode, submitCode } = useActions(oauthDeviceAuthorizeLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    return (
        <AuthScene notes={AUTH_NOTES.oauthDevice.enterCode}>
            <AuthSceneCard
                top={
                    pendingConnection?.flow === 'device' ? (
                        <OAuthConnectionLogos
                            appName={pendingConnection.clientName}
                            logoUri={pendingConnection.logoUri}
                        />
                    ) : undefined
                }
            >
                <AuthCardTitle title="Approve a login" sub="Type the code your terminal shows, like BCDF-GHJK." />
                <form
                    className="flex flex-col gap-4"
                    onSubmit={(event) => {
                        event.preventDefault()
                        submitCode()
                    }}
                >
                    <LemonField.Pure label="Code" error={error}>
                        <LemonInput
                            className="ph-ignore-input font-mono text-lg tracking-wider"
                            autoFocus
                            data-attr="oauth-device-code"
                            placeholder="BCDF-GHJK"
                            maxLength={20}
                            value={userCode}
                            onChange={setUserCode}
                            autoComplete="off"
                            autoCorrect="off"
                            autoCapitalize="characters"
                            spellCheck={false}
                        />
                    </LemonField.Pure>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        data-attr="oauth-device-continue"
                        fullWidth
                        center
                        size="large"
                        loading={deviceGrantLoading || goingToLogin}
                        disabledReason={userCode.trim() ? undefined : 'Type the code first'}
                    >
                        Continue
                    </LemonButton>
                </form>
            </AuthSceneCard>
        </AuthScene>
    )
}
