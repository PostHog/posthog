import React, { useState } from 'react'
import posthog from 'posthog-js'
import { featureFlagLogic } from '../../lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from '../../lib/constants'
import { useValues } from 'kea'
import './RedesignOptIn.scss'
import { preflightLogic } from '../../scenes/PreflightCheck/logic'
import { LemonSwitch } from '../../lib/components/LemonSwitch/LemonSwitch'

export function RedesignOptIn(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)

    const [isSwitchChecked, setIsSwitchChecked] = useState(featureFlags[FEATURE_FLAGS.LEMONADE] as boolean)
    const [isSwitchLoading, setIsSwitchLoading] = useState(false)

    return preflight?.cloud || preflight?.is_debug ? (
        <span className="RedesignOptIn">
            <label htmlFor="redesign-opt-in" className="info">
                {featureFlags[FEATURE_FLAGS.LEMONADE]
                    ? "You're using the new design"
                    : "Try PostHog's navigation redesign!"}
            </label>
            <LemonSwitch
                id="redesign-opt-in"
                onChange={(checked) => {
                    setIsSwitchLoading(true)
                    setIsSwitchChecked(checked)
                    posthog.people.set('opted_into_lemonade', checked, () =>
                        setTimeout(() => {
                            posthog.featureFlags.reloadFeatureFlags()
                            setIsSwitchLoading(false)
                        }, 300)
                    )
                    posthog.capture(checked ? `opted into navigation redesign` : 'opted out of navigation redesign')
                }}
                checked={isSwitchChecked}
                loading={isSwitchLoading}
            />
        </span>
    ) : null
}
