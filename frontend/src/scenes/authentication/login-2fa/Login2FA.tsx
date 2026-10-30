import { useActions, useMountedLogic, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { loginTelemetryLogic } from 'scenes/authentication/shared/loginTelemetryLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { login2FALogic } from './login2FALogic'

// The lead text below is wrapped in a <span>: in-page translation replaces text nodes with <font>
// elements, so inserting the conditional support link beside a bare text node crashes React
// (insertBefore / removeChild NotFoundError, see react#11538).
export function Login2FA(): JSX.Element {
    // Mounted here so the login funnel is only reported from the auth scenes
    useMountedLogic(loginTelemetryLogic)
    const { isTwofactortokenSubmitting, generalError, passkey2FALoading, passkeysAvailable, totpAvailable } =
        useValues(login2FALogic)
    const { beginPasskey2FA } = useActions(login2FALogic)
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    return (
        <AuthScene notes={AUTH_NOTES.login2fa.default}>
            <AuthSceneCard showPendingConnection>
                <AuthCardTitle
                    title="Two-factor authentication"
                    sub={
                        <>
                            <span>Your passkey, an authenticator code or a backup code will do.</span>
                            {preflight?.cloud && (
                                <>
                                    {' '}
                                    <Link
                                        data-attr="2fa-contact-support"
                                        onClick={(e) => {
                                            e.preventDefault()
                                            openSupportForm({
                                                kind: 'support',
                                            })
                                        }}
                                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                                    >
                                        Need help?
                                    </Link>
                                </>
                            )}
                        </>
                    }
                />
                {generalError && (
                    <AuthBanner variant="danger" className="mb-4">
                        {generalError.detail}
                    </AuthBanner>
                )}
                {passkeysAvailable && (
                    <>
                        <LemonButton
                            type="secondary"
                            htmlType="button"
                            onClick={() => beginPasskey2FA()}
                            loading={passkey2FALoading}
                            fullWidth
                            center
                            size="large"
                            icon={<img src={passkeyLogo} alt="Passkey" className="object-contain w-7 h-7" />}
                        >
                            Use passkey
                        </LemonButton>
                        {totpAvailable && <LemonDivider className="my-4" label="or use a code" />}
                    </>
                )}
                {totpAvailable && (
                    <Form
                        logic={login2FALogic}
                        formKey="twofactortoken"
                        enableFormOnSubmit
                        className="flex flex-col gap-4"
                    >
                        <LemonField name="token" label="Authenticator token">
                            <LemonInput
                                className="ph-ignore-input"
                                autoFocus={!passkeysAvailable}
                                data-attr="token"
                                placeholder="123456"
                                inputMode="numeric"
                                autoComplete="one-time-code"
                                fullWidth
                            />
                        </LemonField>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            data-attr="2fa-login"
                            fullWidth
                            center
                            loading={isTwofactortokenSubmitting}
                            size="large"
                        >
                            Log in
                        </LemonButton>
                    </Form>
                )}
                {!passkeysAvailable && !totpAvailable && (
                    <AuthBanner variant="danger">
                        No 2FA methods available. Please contact support if you believe this is an error.
                    </AuthBanner>
                )}
            </AuthSceneCard>
        </AuthScene>
    )
}

export const scene: SceneExport = {
    component: Login2FA,
    logic: login2FALogic,
}
