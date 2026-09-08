import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { ConceptWaitlistCTA } from 'lib/components/FeaturePreviews/ConceptWaitlistCTA'
import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'

// pinned: localStorage key, because renaming it shows the banner again to everyone who closed it
const DISMISS_KEY = 'behavioral-cohorts-waitlist'

export function BehavioralCohortsWaitlistBanner(): JSX.Element | null {
    const { earlyAccessFeatures } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures } = useActions(featurePreviewsLogic)

    useEffect(() => {
        loadEarlyAccessFeatures()
    }, [loadEarlyAccessFeatures])

    // The early access feature decides whether the banner shows. It appears once the concept
    // feature exists, and stops showing when the feature leaves the concept ("coming soon")
    // stage, so shipping behavioral cohorts does not need a second frontend change.
    const feature = earlyAccessFeatures.find((f) => f.flagKey === FEATURE_FLAGS.BEHAVIORAL_COHORTS)
    if (feature?.stage !== 'concept') {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey={DISMISS_KEY}>
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-semibold">Behavioral cohorts are coming soon</span>
                    <LemonTag type="completion">Beta</LemonTag>
                </div>
                <p className="m-0">
                    Group people by the actions they took, and keep the group up to date as they take them. Join the
                    waitlist to try it first.
                </p>
                <ConceptWaitlistCTA feature={feature} />
            </div>
        </LemonBanner>
    )
}
