import React from 'react'
import { Switch } from 'antd'
import posthog from 'posthog-js'
import { featureFlagLogic } from '../../lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from '../../lib/constants'
import { useValues } from 'kea'
import './RedesignOptIn.scss'

export function RedesignOptIn(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <span className="RedesignOptIn">
            <span className="info">
                {featureFlags[FEATURE_FLAGS.LEMONADE]
                    ? "You're using the new design"
                    : "Try out PostHog's navigation redesign!"}
            </span>
            <Switch
                size="small"
                onChange={(checked) => {
                    posthog.people.set('opted_into_lemonade', checked, () =>
                        setTimeout(() => posthog.featureFlags.reloadFeatureFlags(), 200)
                    )
                }}
                checked={featureFlags[FEATURE_FLAGS.LEMONADE] as boolean}
            />
        </span>
    )
}
