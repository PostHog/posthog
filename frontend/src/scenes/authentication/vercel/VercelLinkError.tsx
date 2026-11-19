import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

export const scene: SceneExport = {
    component: VercelLinkError,
}

export function VercelLinkError(): JSX.Element {
    const { searchParams } = useValues(router)
    const { logout } = useActions(userLogic)

    const expectedEmail = searchParams.expected_email
    const currentEmail = searchParams.current_email || 'your current account'
    const code = searchParams.code
    const state = searchParams.state

    const nextUrl =
        code && state
            ? `/login/vercel?mode=sso&code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`
            : null

    return (
        <AuthScene notes={AUTH_NOTES.accountMismatch.default}>
            <AuthSceneCard>
                <AuthCardTitle title="Account mismatch" sub="Let's get you into the right one." />
                <div className="flex flex-col gap-3">
                    <AuthBanner variant="warning">
                        <p className="m-0 mb-1.5">
                            <span>You're currently logged in as</span> <strong>{currentEmail}</strong>
                            <span>, but your Vercel account is linked to</span>{' '}
                            {expectedEmail ? <strong>{expectedEmail}</strong> : <span>a different account</span>}
                            <span>.</span>
                        </p>
                        <p className="m-0">
                            To complete Vercel SSO, please log out and sign in with the correct account.
                        </p>
                    </AuthBanner>
                    <LemonButton
                        fullWidth
                        type="primary"
                        center
                        size="large"
                        onClick={() => logout(false, nextUrl ?? undefined)}
                    >
                        {expectedEmail ? `Log out and continue with ${expectedEmail}` : 'Log out and continue'}
                    </LemonButton>
                    <LemonButton fullWidth type="secondary" center size="large" to="/">
                        Cancel
                    </LemonButton>
                </div>
            </AuthSceneCard>
        </AuthScene>
    )
}

export default VercelLinkError
