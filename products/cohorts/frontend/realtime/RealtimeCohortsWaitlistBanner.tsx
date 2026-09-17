import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { ConceptWaitlistCTA } from 'lib/components/FeaturePreviews/ConceptWaitlistCTA'
import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'

// pinned: localStorage key, because renaming it shows the banner again to everyone who closed it
const DISMISS_KEY = 'realtime-cohorts-waitlist'

export function RealtimeCohortsWaitlistBanner(): JSX.Element | null {
    const { earlyAccessFeatures } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures } = useActions(featurePreviewsLogic)
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: DISMISS_KEY }))
    // A team that can already target flags with realtime cohorts sees "Realtime" tags in the
    // table below; a waitlist above them would contradict the page.
    const alreadyHasRealtimeCohorts = useFeatureFlag('REALTIME_COHORT_FLAG_TARGETING')
    const hidden = isDismissed || alreadyHasRealtimeCohorts

    // The loader forces a fresh request, so only ask when the banner could render.
    useEffect(() => {
        if (!hidden) {
            loadEarlyAccessFeatures()
        }
    }, [hidden, loadEarlyAccessFeatures])

    // Shipping realtime cohorts retires this banner on its own: the early access feature
    // leaving the concept ("coming soon") stage hides it, with no second frontend change.
    const feature = earlyAccessFeatures.find((f) => f.flagKey === FEATURE_FLAGS.REALTIME_COHORTS)
    if (hidden || feature?.stage !== 'concept') {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey={DISMISS_KEY} alignItems="start">
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-semibold">Realtime cohorts are coming soon</span>
                    <LemonTag type="completion">Beta</LemonTag>
                </div>
                <p className="m-0">
                    Group people by the actions they took, and keep the group up to date as they take them. Join the
                    waitlist to try it first.
                </p>
                <ConceptWaitlistCTA feature={feature} dataAttr="realtime-cohorts-waitlist-signup" />
            </div>
        </LemonBanner>
    )
}
