import { useActions, useValues } from 'kea'

import { LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { webAnalyticsLogic } from './webAnalyticsLogic'

export const IncludeHostToggle = (): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { includeHostPath } = useValues(webAnalyticsLogic)
    const { setIncludeHostPath } = useActions(webAnalyticsLogic)

    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_INCLUDE_HOST]) {
        return null
    }

    return (
        <Tooltip title="Show the full host + path (e.g. example.com/about) instead of just the path">
            <div className="flex items-center gap-1">
                <LemonSwitch
                    checked={includeHostPath}
                    onChange={setIncludeHostPath}
                    className="text-xs"
                    label="Include host"
                />
            </div>
        </Tooltip>
    )
}
