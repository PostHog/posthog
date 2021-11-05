import React from 'react'
import { Switch } from 'antd'
import posthog from 'posthog-js'
import { featureFlagLogic } from '../../lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from '../../lib/constants'
import { useValues } from 'kea'
import './RedesignOptIn.scss'
import { preflightLogic } from '../../scenes/PreflightCheck/logic'

export function RedesignOptIn(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)

    return preflight?.cloud || preflight?.is_debug ? (
        <span className="RedesignOptIn">
            <label htmlFor="redesign-opt-in" className="info">
                {featureFlags[FEATURE_FLAGS.LEMONADE]
                    ? "You're using the new design"
                    : "Try PostHog's navigation redesign!"}
            </label>
            <Switch
                // @ts-expect-error - id works just fine despite not being in CompoundedComponent
                id="redesign-opt-in"
                size="small"
                onChange={(checked) => {
                    posthog.people.set('opted_into_lemonade', checked, () =>
                        setTimeout(() => posthog.featureFlags.reloadFeatureFlags(), 200)
                    )
                    posthog.capture(checked ? `opted into navigation redesign` : 'opted out of navigation redesign')
                }}
                checked={featureFlags[FEATURE_FLAGS.LEMONADE] as boolean}
            />
        </span>
    ) : null
}
