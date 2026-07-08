import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { loginLogic } from './loginLogic'

export function SessionRiskBanner({ className }: { className?: string }): JSX.Element | null {
    const { wasSignedOutForSessionRisk } = useValues(loginLogic)

    if (!wasSignedOutForSessionRisk) {
        return null
    }

    return (
        <LemonBanner type="warning" className={className}>
            For your security, we signed you out because this session showed unusual activity. Sign back in to continue.
        </LemonBanner>
    )
}
