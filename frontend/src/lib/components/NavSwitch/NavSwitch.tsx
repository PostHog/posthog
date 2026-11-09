import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export type NavSwitchSurface = 'today_sidebar' | 'navbar' | 'org_menu' | 'account_menu'

export interface NavSwitch {
    available: boolean
    newNavOn: boolean
    switchNav: (surface: NavSwitchSurface) => void
    giveFeedback: (surface: NavSwitchSurface) => void
}

export function useNavSwitch(): NavSwitch {
    const { featureFlags } = useValues(featureFlagLogic)
    const { earlyAccessFeatures } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures, updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)
    const newNavOn = !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
    const switchAvailable = !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV_SWITCH]
    // The old navigation shows the switch only when the early access feature exists, so the list loads
    // there. The new navigation skips the call, where the feature only supplies stage metadata.
    useEffect(() => {
        if (switchAvailable && !newNavOn) {
            loadEarlyAccessFeatures()
        }
    }, [switchAvailable, newNavOn, loadEarlyAccessFeatures])
    const todayNavFeature = earlyAccessFeatures.find((feature) => feature.flagKey === FEATURE_FLAGS.TODAY_RAIL_NAV)
    return {
        available: switchAvailable && (newNavOn || !!todayNavFeature),
        newNavOn,
        switchNav: (surface) => {
            // pinned: analytics event names and properties. The exit survey triggers on the off event.
            posthog.capture(newNavOn ? 'today nav switched off' : 'today nav switched on', { surface })
            updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.TODAY_RAIL_NAV, !newNavOn, todayNavFeature?.stage)
            lemonToast.success(
                newNavOn
                    ? 'You are back on the old navigation. Switch to the new navigation any time.'
                    : 'New navigation is on. Switch back any time.'
            )
        },
        giveFeedback: (surface) => {
            // pinned: analytics event name and properties. The navigation feedback survey triggers on it.
            posthog.capture('today nav feedback clicked', { surface, nav: newNavOn ? 'new' : 'old' })
        },
    }
}

/** The switch swaps the chrome in place through the enrollment update, so no reload is needed. */
export function NavSwitchButtons({ surface }: { surface: NavSwitchSurface }): JSX.Element | null {
    const { available, newNavOn, switchNav, giveFeedback } = useNavSwitch()
    if (!available) {
        return null
    }
    return (
        <div className="flex flex-col gap-1">
            <LemonButton
                type="secondary"
                size="small"
                center
                fullWidth
                onClick={() => switchNav(surface)}
                data-attr="nav-switch-button"
            >
                {newNavOn ? 'Use old navigation' : 'Use new navigation'}
            </LemonButton>
            <LemonButton
                type="tertiary"
                size="small"
                center
                fullWidth
                onClick={() => giveFeedback(surface)}
                data-attr="nav-feedback-button"
            >
                Give feedback
            </LemonButton>
        </div>
    )
}
