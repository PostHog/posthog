import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { ConceptWaitlistCTA } from 'lib/components/FeaturePreviews/ConceptWaitlistCTA'
import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { areClientFeatureFlagsHonored } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { cohortsSetupLogic } from '../emptyState/cohortsSetupLogic'
import { useRealtimeCohortsServing } from './useRealtimeCohortsServing'

// pinned: localStorage key, because renaming it shows the banner again to everyone who closed it
const WAITLIST_DISMISS_KEY = 'realtime-cohorts-waitlist'
const BETA_DISMISS_KEY = 'realtime-cohorts-beta-opt-in'
const REALTIME_COHORTS_DOCS_URL = 'https://posthog.com/docs/data/realtime-cohorts'

function enrolledInThisBrowser(): boolean {
    const storedPersonProps = posthog.get_property('$stored_person_properties') as Record<string, unknown> | undefined
    return !!storedPersonProps?.[`$feature_enrollment/${FEATURE_FLAGS.REALTIME_COHORTS}`]
}

function bannerFor(
    feature: EnrichedEarlyAccessFeature,
    waitlistDismissed: boolean,
    betaDismissed: boolean
): 'beta' | 'concept' | null {
    if (feature.enabled) {
        return null
    }
    if (feature.stage === 'beta') {
        return betaDismissed ? null : 'beta'
    }
    if (feature.stage === 'concept') {
        return waitlistDismissed ? null : 'concept'
    }
    return null
}

export function RealtimeCohortsWaitlistBanner(): JSX.Element | null {
    const { earlyAccessFeatures } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures, updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)
    const { preflight } = useValues(preflightLogic)
    const { isDismissed: waitlistDismissed } = useValues(lemonBannerLogic({ dismissKey: WAITLIST_DISMISS_KEY }))
    const { isDismissed: betaDismissed } = useValues(lemonBannerLogic({ dismissKey: BETA_DISMISS_KEY }))
    // Teams with no cohorts get the setup screen today; this keeps them out if it becomes skippable.
    const { setupStatus } = useValues(cohortsSetupLogic)
    // A team with realtime cohort targeting sees "Realtime" tags in the table below; a waitlist
    // above them would contradict the page.
    const alreadyHasRealtimeCohorts = useRealtimeCohortsServing()
    const hidden =
        (waitlistDismissed && betaDismissed) ||
        !areClientFeatureFlagsHonored(preflight) ||
        alreadyHasRealtimeCohorts ||
        setupStatus !== 'has-data' ||
        enrolledInThisBrowser()

    // The loader forces a fresh request, so only ask when the banner could render.
    useEffect(() => {
        if (!hidden) {
            loadEarlyAccessFeatures()
        }
    }, [hidden, loadEarlyAccessFeatures])

    const feature = earlyAccessFeatures.find((f) => f.flagKey === FEATURE_FLAGS.REALTIME_COHORTS)
    if (hidden || !feature) {
        return null
    }
    const banner = bannerFor(feature, waitlistDismissed, betaDismissed)
    if (!banner) {
        return null
    }

    if (banner === 'beta') {
        return (
            <PostHogCaptureOnViewed name="realtime-cohorts-beta-opt-in-banner-shown">
                <LemonBanner type="info" dismissKey={BETA_DISMISS_KEY} alignItems="start">
                    <div className="flex flex-col gap-2">
                        <span className="font-semibold">Realtime cohorts are in beta</span>
                        <p className="m-0">
                            Group people by the actions they took, and keep the group up to date as they take them, so
                            feature flags can target that group. Joining turns on the beta for everyone in this project.
                        </p>
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                // pinned: data-attr, because autocapture insights find the opt-in click by it
                                data-attr="realtime-cohorts-beta-opt-in"
                                // Enrollment turns the flag on in this browser, and realtimeCohortsJoinLogic reacts to
                                // the flag by joining the project.
                                onClick={() => {
                                    updateEarlyAccessFeatureEnrollment(feature.flagKey, true, feature.stage)
                                    if (!window.IMPERSONATED_SESSION) {
                                        lemonToast.success("Realtime cohorts: you've joined the beta.", {
                                            button: {
                                                label: 'Learn more',
                                                action: () =>
                                                    window.open(REALTIME_COHORTS_DOCS_URL, '_blank', 'noopener'),
                                                dataAttr: 'realtime-cohorts-beta-toast-docs',
                                            },
                                        })
                                    }
                                }}
                            >
                                Join the beta
                            </LemonButton>
                            <LemonButton
                                type="tertiary"
                                size="small"
                                to={REALTIME_COHORTS_DOCS_URL}
                                targetBlank
                                data-attr="realtime-cohorts-beta-banner-docs"
                            >
                                Learn more
                            </LemonButton>
                        </div>
                    </div>
                </LemonBanner>
            </PostHogCaptureOnViewed>
        )
    }

    return (
        <PostHogCaptureOnViewed name="realtime-cohorts-waitlist-banner-shown">
            <LemonBanner type="info" dismissKey={WAITLIST_DISMISS_KEY} alignItems="start">
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-semibold">Real-time cohorts are coming soon</span>
                        <LemonTag type="completion">Beta</LemonTag>
                    </div>
                    <p className="m-0">
                        Group people by the actions they took, and keep the group up to date as they take them. Join the
                        waitlist to try it first.
                    </p>
                    <ConceptWaitlistCTA
                        feature={feature}
                        dataAttr="realtime-cohorts-waitlist-signup"
                        collectEmail={false}
                        // Signing up flips `feature.enabled` and unmounts the banner, so its inline
                        // confirmation never shows; the toast outlives it.
                        onSignUp={() =>
                            lemonToast.success(
                                "You're on the real-time cohorts waitlist. We'll email you when it's ready."
                            )
                        }
                    />
                </div>
            </LemonBanner>
        </PostHogCaptureOnViewed>
    )
}
