import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

export function SessionReplayOverLimitBanner(): JSX.Element | null {
    const { isProductOverUsageLimit } = useValues(billingLogic)

    if (!isProductOverUsageLimit(ProductKey.SESSION_REPLAY)) {
        return null
    }

    return (
        <PostHogCaptureOnViewed name="replay-over-limit-banner-shown">
            <LemonBanner
                type="warning"
                action={{
                    children: 'Increase billing limit',
                    to: urls.organizationBilling([ProductKey.SESSION_REPLAY]),
                    'data-attr': 'replay-over-limit-banner-cta',
                }}
            >
                You're over your session replay usage limit, so new recordings aren't being ingested. Recent recordings
                may be missing from the list, and recordings captured while over the limit can't be played.{' '}
                <Link to="https://posthog.com/docs/session-replay/troubleshooting" target="_blank">
                    Learn more
                </Link>
                .
            </LemonBanner>
        </PostHogCaptureOnViewed>
    )
}
