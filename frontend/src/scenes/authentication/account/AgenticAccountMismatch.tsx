import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { submitLogoutForm } from 'scenes/authentication/shared/logout'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: AgenticAccountMismatch,
}

export function AgenticAccountMismatch(): JSX.Element {
    const { searchParams } = useValues(router)

    const expectedEmail = typeof searchParams.expected_email === 'string' ? searchParams.expected_email : ''
    const currentEmail =
        typeof searchParams.current_email === 'string' ? searchParams.current_email : 'your current account'
    const partnerName = typeof searchParams.partner_name === 'string' ? searchParams.partner_name : 'the requesting app'
    const state = typeof searchParams.state === 'string' ? searchParams.state : ''

    const nextUrl = state ? `/api/agentic/authorize?state=${encodeURIComponent(state)}` : null

    return (
        <BridgePage view="agentic-account-mismatch">
            <div className="text-center mb-4">
                <IconErrorOutline className="text-warning text-4xl" />
            </div>
            <h2 className="text-center">Account mismatch</h2>
            <div className="text-center mb-6">
                <p className="mb-2">
                    You're currently logged in as <strong>{currentEmail}</strong>, but your {partnerName} account is
                    linked to {expectedEmail ? <strong>{expectedEmail}</strong> : 'a different PostHog account'}.
                </p>
                <p>To continue, log out and sign in with the correct email.</p>
            </div>
            <div className="flex flex-col gap-2">
                <LemonButton fullWidth type="primary" center onClick={() => submitLogoutForm(nextUrl)}>
                    {expectedEmail ? `Log out and continue as ${expectedEmail}` : 'Log out and continue'}
                </LemonButton>
                <LemonButton fullWidth type="secondary" center to="/">
                    Cancel
                </LemonButton>
            </div>
        </BridgePage>
    )
}

export default AgenticAccountMismatch
