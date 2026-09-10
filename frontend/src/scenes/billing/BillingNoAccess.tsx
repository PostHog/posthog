import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

interface BillingNoAccessProps {
    title?: string
    reason: string
    onRetry: () => void
    retryLoading: boolean
}

export function BillingNoAccess({
    title = 'Billing',
    reason,
    onRetry,
    retryLoading,
}: BillingNoAccessProps): JSX.Element {
    return (
        <div className="deprecated-space-y-4">
            <h1>{title}</h1>
            <LemonBanner type="warning">
                {`${reason} If an admin changed your access just now, check again to pick it up.`}
            </LemonBanner>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    onClick={onRetry}
                    loading={retryLoading}
                    data-attr="billing-no-access-check-again"
                >
                    Check again
                </LemonButton>
                <LemonButton type="secondary" to={urls.default()}>
                    Go back home
                </LemonButton>
            </div>
        </div>
    )
}
