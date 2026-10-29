import { useActions, useValues } from 'kea'
import { type ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES, type AuthNotes } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { twoFactorResetLogic } from './twoFactorResetLogic'

export const scene: SceneExport = {
    component: TwoFactorReset,
    logic: twoFactorResetLogic,
}

function TwoFactorResetCard({
    title,
    sub,
    notes = AUTH_NOTES.twoFactorReset.reset,
    children,
}: {
    title: string
    sub?: string
    notes?: AuthNotes
    children: ReactNode
}): JSX.Element {
    return (
        <AuthScene notes={notes}>
            <AuthSceneCard>
                <AuthCardTitle title={title} sub={sub} />
                <div className="flex flex-col gap-3">{children}</div>
            </AuthSceneCard>
        </AuthScene>
    )
}

export function TwoFactorReset(): JSX.Element {
    const {
        validatedResetToken,
        validatedResetTokenLoading,
        resetComplete,
        resetError,
        resetLoading,
        requiresLogin,
        loginRedirectUrl,
    } = useValues(twoFactorResetLogic)
    const { confirmReset } = useActions(twoFactorResetLogic)

    if (validatedResetTokenLoading) {
        return (
            <TwoFactorResetCard title="Checking your reset link…">
                <div className="flex justify-center">
                    <Spinner className="text-2xl" />
                </div>
            </TwoFactorResetCard>
        )
    }

    if (requiresLogin) {
        return (
            <TwoFactorResetCard title="Log in first" sub="Use your email and password, then we'll reset your 2FA.">
                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    size="large"
                    data-attr="login-to-reset"
                    to={loginRedirectUrl}
                >
                    Log in to continue
                </LemonButton>
            </TwoFactorResetCard>
        )
    }

    if (resetComplete) {
        return (
            <TwoFactorResetCard
                title="2FA has been reset"
                sub="You can log in without 2FA now."
                notes={AUTH_NOTES.twoFactorReset.done}
            >
                <AuthBanner variant="note">
                    We recommend setting up 2FA again after logging in to keep your account secure.
                </AuthBanner>
                <LemonButton fullWidth type="primary" center size="large" data-attr="back-to-login" to={urls.login()}>
                    Log in
                </LemonButton>
            </TwoFactorResetCard>
        )
    }

    if (!validatedResetToken?.success) {
        return (
            <TwoFactorResetCard title="Unable to reset 2FA" notes={AUTH_NOTES.twoFactorReset.invalid}>
                <AuthBanner variant="danger">
                    {validatedResetToken?.error ||
                        'This reset link is invalid or has expired. Please contact your administrator to request a new link.'}
                </AuthBanner>
                <LemonButton fullWidth type="primary" center size="large" data-attr="back-to-login" to={urls.login()}>
                    Back to login
                </LemonButton>
            </TwoFactorResetCard>
        )
    }

    return (
        <TwoFactorResetCard title="Reset two-factor authentication" sub="After this, you'll log in again.">
            <AuthBanner variant="note">
                <p className="m-0 mb-1.5 font-semibold text-primary">This will:</p>
                <ul className="m-0 pl-4 list-disc">
                    <li>Remove your TOTP authenticator device</li>
                    <li>Delete your backup codes</li>
                    <li>Disable passkey-based 2FA (your passkeys will still work for login)</li>
                </ul>
            </AuthBanner>
            {resetError && <AuthBanner variant="danger">{resetError}</AuthBanner>}
            <LemonButton
                fullWidth
                type="primary"
                status="danger"
                center
                size="large"
                data-attr="confirm-2fa-reset"
                loading={resetLoading}
                onClick={() => confirmReset(validatedResetToken.token!)}
            >
                Confirm and reset 2FA
            </LemonButton>
            <LemonButton fullWidth type="secondary" center size="large" data-attr="cancel-2fa-reset" to={urls.login()}>
                Cancel
            </LemonButton>
        </TwoFactorResetCard>
    )
}
