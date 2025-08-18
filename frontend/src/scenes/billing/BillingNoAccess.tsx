import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

interface BillingNoAccessProps {
    title?: string
    reason: string
}

export function BillingNoAccess({ title = 'Billing', reason }: BillingNoAccessProps): JSX.Element {
    return (
        <div className="deprecated-space-y-4">
            <h1>{title}</h1>
            <LemonBanner type="warning">{reason}</LemonBanner>
            <div className="flex">
                <LemonButton type="primary" to={urls.default()}>
                    Go back home
                </LemonButton>
            </div>
        </div>
    )
}
