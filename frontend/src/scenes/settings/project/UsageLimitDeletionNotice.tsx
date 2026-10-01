import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'

/**
 * Usage limits are organization-scoped, so people who hit one often delete or recreate a project
 * expecting ingestion to resume. Say here that it will not, and name the steps that do work.
 */
export function UsageLimitDeletionNotice(): JSX.Element | null {
    const { billing, billingLoading, productsAtOrOverUsageLimit } = useValues(billingLogic)
    const { loadBilling } = useActions(billingLogic)
    const [billingRequested, setBillingRequested] = useState(false)

    // Nothing on the settings path loads billing, and an empty product list reads the same as
    // "no limit reached", so ask for it once rather than hide the notice from a limited org.
    useEffect(() => {
        if (!billing) {
            loadBilling()
            setBillingRequested(true)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    if (!billing) {
        // Hold the space while the answer is unknown. A failed load leaves nothing to say, which
        // is what an instance without billing gets.
        return billingLoading || !billingRequested ? <LemonSkeleton className="h-12 mt-2" /> : null
    }

    if (productsAtOrOverUsageLimit.length === 0) {
        return null
    }
    const isErrorTrackingLimited = productsAtOrOverUsageLimit.some((product) => product.type === 'error_tracking')

    return (
        <p className="mt-2 p-2 bg-bg-3000 rounded text-sm">
            <strong>Your organization has reached a usage limit.</strong> Usage counts across the whole organization, so
            a new project shares the same limit and deleting this one does not give the usage back. To start ingesting
            again, <Link to={urls.organizationBilling()}>raise or remove the limit</Link>
            {isErrorTrackingLimited && (
                <>
                    , then add a{' '}
                    <Link
                        to={urls.settings(
                            'environment-error-tracking-configuration',
                            'error-tracking-suppression-rules'
                        )}
                    >
                        suppression rule
                    </Link>{' '}
                    so the same errors cannot use the allowance again
                </>
            )}
            .
        </p>
    )
}
