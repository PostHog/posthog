import { useValues } from 'kea'

import { PostHogCaptureOnViewed } from '@posthog/react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { urls } from 'scenes/urls'

const REPLAY_VISION_PROMO_DISMISS_KEY = 'replay-vision-launch-promo'

export function ReplayVisionPromoBanner({
    source,
    className,
}: {
    /** Which surface rendered the banner, sent on the impression event so surfaces can be compared. */
    source: string
    className?: string
}): JSX.Element | null {
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: REPLAY_VISION_PROMO_DISMISS_KEY }))
    const hasReplayVision = useFeatureFlag('REPLAY_VISION')

    // Without the flag the CTA would land on a 404, so don't advertise the feature at all.
    // A dismissed LemonBanner renders null but the viewed tracker would still fire, skewing impressions
    if (!hasReplayVision || isDismissed) {
        return null
    }

    return (
        <PostHogCaptureOnViewed name="replay-vision-launch-banner-shown" properties={{ source }}>
            <LemonBanner
                type="ai"
                className={className}
                dismissKey={REPLAY_VISION_PROMO_DISMISS_KEY}
                action={{
                    children: 'Try Replay vision',
                    to: urls.replayVision(),
                    center: true,
                    'data-attr': 'replay-vision-launch-banner-cta',
                }}
            >
                Replay vision is here. Scanners watch your recordings for you and surface what matters.
            </LemonBanner>
        </PostHogCaptureOnViewed>
    )
}
