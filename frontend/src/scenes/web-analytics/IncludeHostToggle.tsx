import { useActions, useValues } from 'kea'

import { LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { webAnalyticsLogic } from './webAnalyticsLogic'

export const IncludeHostToggle = (): JSX.Element => {
    const { includeHostPath } = useValues(webAnalyticsLogic)
    const { setIncludeHostPath } = useActions(webAnalyticsLogic)

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
