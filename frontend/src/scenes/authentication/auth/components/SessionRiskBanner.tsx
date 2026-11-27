import { useValues } from 'kea'

import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'

import { loginLogic } from '../loginLogic'

export function SessionRiskBanner({ className }: { className?: string }): JSX.Element | null {
    const { wasSignedOutForSessionRisk, wasSignedOutForUnboundSession } = useValues(loginLogic)

    const message = wasSignedOutForUnboundSession
        ? 'For your security, we signed you out because this session was used without the device you signed in on. Sign back in to continue.'
        : wasSignedOutForSessionRisk
          ? 'For your security, we signed you out because this session showed unusual activity. Sign back in to continue.'
          : null

    if (message === null) {
        return null
    }

    return (
        <AuthBanner variant="warning" className={className}>
            {message}
        </AuthBanner>
    )
}
