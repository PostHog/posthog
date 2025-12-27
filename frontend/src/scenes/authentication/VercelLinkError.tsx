import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: VercelLinkError,
}

export function VercelLinkError(): JSX.Element {
    const { searchParams } = useValues(router)

    const expectedEmail = searchParams.expected_email
    const currentEmail = searchParams.current_email || 'your current account'
    const code = searchParams.code
    const state = searchParams.state

    const nextUrl =
        code && state
            ? `/login/vercel?mode=sso&code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`
            : null
    const logoutUrl = nextUrl ? `/logout?next=${encodeURIComponent(nextUrl)}` : '/logout'

    return (
        <BridgePage view="vercel-link-error">
            <div className="text-center mb-4">
                <IconErrorOutline className="text-warning text-4xl" />
            </div>
            <h2 className="text-center">Account mismatch</h2>
            <div className="text-center mb-6">
                <p className="mb-2">
                    You're currently logged in as <strong>{currentEmail}</strong>, but your Vercel account is linked to{' '}
                    {expectedEmail ? <strong>{expectedEmail}</strong> : 'a different account'}.
                </p>
                <p>To complete Vercel SSO, please log out and sign in with the correct account.</p>
            </div>
            <div className="flex flex-col gap-2">
                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    onClick={() => {
                        window.location.href = logoutUrl
                    }}
                >
                    {expectedEmail ? `Log out and continue with ${expectedEmail}` : 'Log out and continue'}
                </LemonButton>
                <LemonButton fullWidth type="secondary" center to="/">
                    Cancel
                </LemonButton>
            </div>
        </BridgePage>
    )
}

export default VercelLinkError
