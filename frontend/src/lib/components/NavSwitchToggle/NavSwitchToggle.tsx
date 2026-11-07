import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonSwitch, lemonToast } from '@posthog/lemon-ui'

import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

/**
 * A visible on/off switch between the navigations. On means the new navigation, and flipping it swaps
 * the chrome in place: the enrollment update rewrites the flag locally, so no reload is needed.
 */
export function NavSwitchToggle({ surface }: { surface: 'today_top_bar' | 'navbar' }): JSX.Element | null {
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
    if (!switchAvailable || (!newNavOn && !todayNavFeature)) {
        return null
    }
    return (
        <LemonSwitch
            checked={newNavOn}
            onChange={(checked) => {
                // pinned: analytics event names and properties. The exit survey triggers on the off event.
                posthog.capture(checked ? 'today nav switched on' : 'today nav switched off', { surface })
                updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.TODAY_RAIL_NAV, checked, todayNavFeature?.stage)
                lemonToast.success(
                    checked
                        ? 'New navigation is on. Turn it off here any time.'
                        : 'You are back on the old navigation. Turn the new navigation on here any time.'
                )
            }}
            label="New navigation"
            size="small"
            bordered
            data-attr="nav-switch-toggle"
        />
    )
}
