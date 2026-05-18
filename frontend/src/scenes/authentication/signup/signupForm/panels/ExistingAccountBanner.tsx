import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { getRelativeNextPath } from 'lib/utils'
import { urls } from 'scenes/urls'

const buildUrlWithParams = (path: string, params: Record<string, string>): string => {
    const query = new URLSearchParams(params).toString()
    return query ? `${path}?${query}` : path
}

export function ExistingAccountBanner({ email }: { email: string }): JSX.Element {
    const { searchParams } = useValues(router)
    const nextParam = getRelativeNextPath(searchParams['next'], location)
    const loginParams: Record<string, string> = { email }
    if (nextParam) {
        loginParams.next = nextParam
    }
    const loginHref = buildUrlWithParams(urls.login(), loginParams)
    const resetHref = buildUrlWithParams(urls.passwordReset(), { email })

    return (
        <LemonBanner type="warning" className="Signup__panel__existing-account">
            <div className="deprecated-space-y-2">
                <p className="mb-0">
                    An account with <b>{email}</b> already exists.
                </p>
                <div className="flex flex-col gap-2 sm:flex-row">
                    <LemonButton
                        type="primary"
                        status="alt"
                        center
                        fullWidth
                        size="small"
                        to={loginHref}
                        data-attr="existing-account-log-in"
                    >
                        Log in with this email
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        center
                        fullWidth
                        size="small"
                        to={resetHref}
                        data-attr="existing-account-reset-password"
                    >
                        Reset password
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
