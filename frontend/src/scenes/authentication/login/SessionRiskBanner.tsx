import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { loginLogic } from './loginLogic'

export function SessionRiskBanner({ className }: { className?: string }): JSX.Element | null {
    const { wasSignedOutForSessionRisk, sessionExpiredRedirectPath } = useValues(loginLogic)

    if (wasSignedOutForSessionRisk) {
        return (
            <LemonBanner type="warning" className={className}>
                For your security, we signed you out because this session showed unusual activity. Sign back in to
                continue.
            </LemonBanner>
        )
    }

    if (sessionExpiredRedirectPath) {
        return (
            <LemonBanner type="info" className={className}>
                Your session expired. Sign in again to get back to {sessionExpiredRedirectPath}.
            </LemonBanner>
        )
    }

    return null
}
