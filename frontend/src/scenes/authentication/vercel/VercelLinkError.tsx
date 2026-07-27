import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
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
    const submitLogout = (): void => {
        const form = document.createElement('form')
        form.method = 'POST'
        form.action = '/logout'
        form.style.display = 'none'

        const csrfInput = document.createElement('input')
        csrfInput.type = 'hidden'
        csrfInput.name = 'csrfmiddlewaretoken'
        csrfInput.value = getCookie('posthog_csrftoken') || ''
        form.appendChild(csrfInput)

        if (nextUrl) {
            const nextInput = document.createElement('input')
            nextInput.type = 'hidden'
            nextInput.name = 'next'
            nextInput.value = nextUrl
            form.appendChild(nextInput)
        }

        document.body.appendChild(form)
        form.submit()
    }

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
                <LemonButton fullWidth type="primary" center onClick={submitLogout}>
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
