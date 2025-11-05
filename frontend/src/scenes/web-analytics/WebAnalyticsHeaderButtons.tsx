import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBolt } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Popover } from 'lib/lemon-ui/Popover'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { WebAnalyticsMenu } from 'scenes/web-analytics/WebAnalyticsMenu'

export function WebAnalyticsHeaderButtons(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [showPopover, setShowPopover] = useState(false)

    const hasFeatureFlag = featureFlags[FEATURE_FLAGS.SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES]
    const isUsingNewEngine = currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables

    const handleToggleEngine = (checked: boolean): void => {
        updateCurrentTeam({
            modifiers: {
                ...currentTeam?.modifiers,
                useWebAnalyticsPreAggregatedTables: checked,
            },
        })
    }

    return (
        <div className="flex items-center gap-2">
            {hasFeatureFlag && (
                <Popover
                    visible={showPopover}
                    onClickOutside={() => setShowPopover(false)}
                    overlay={
                        <div className="p-4 max-w-160">
                            <div className="flex items-center gap-2 mb-2">
                                <h3 className="font-semibold flex items-center gap-2">
                                    About the New Query Engine
                                    <LemonTag type="warning" className="uppercase">
                                        Beta
                                    </LemonTag>
                                </h3>
                            </div>
                            <p className="mb-3">
                                Our new Web Analytics Query Engine powers faster queries using pre-aggregated data,
                                giving you quicker access to insights and it's much better at handling large datasets.
                            </p>

                            <div className="mb-3">
                                <strong>A few things to note:</strong>
                                <ul className="list-disc ml-4 mt-1 space-y-1">
                                    <li>
                                        Some filters may not yet be supported, but we're working on expanding coverage.
                                    </li>
                                    <li>
                                        We use smart approximation techniques to keep performance high, and we aim for
                                        less than 1% difference compared to exact results.
                                    </li>
                                    <li>
                                        You can toggle the engine on or off directly from this interface if you want to
                                        compare results or prefer the previous method.
                                    </li>
                                    <li>Results are currently tied to UTC timezone for query and display.</li>
                                </ul>
                            </div>

                            <div className="mb-3">
                                <strong>Coming Soon:</strong>
                                <ul className="list-disc ml-4 mt-1 space-y-1">
                                    <li>Use the new engine for chart visualizations</li>
                                    <li>Support for channel types in breakdowns</li>
                                    <li>Enable conversion goals</li>
                                    <li>Further improvements in accuracy</li>
                                    <li>More filters!</li>
                                </ul>
                            </div>
                        </div>
                    }
                >
                    <div
                        className="flex items-center gap-2 cursor-pointer"
                        onClick={() => handleToggleEngine(!isUsingNewEngine)}
                        onMouseEnter={() => setShowPopover(true)}
                        onMouseLeave={() => setShowPopover(false)}
                    >
                        <IconBolt className={isUsingNewEngine ? 'text-warning' : 'text-muted'} />
                        <span className="text-sm font-medium">
                            {isUsingNewEngine ? 'New Query Engine' : 'Regular Query Engine'}
                        </span>
                        <LemonSwitch checked={!!isUsingNewEngine} onChange={handleToggleEngine} size="small" />
                    </div>
                </Popover>
            )}
            <WebAnalyticsMenu />
        </div>
    )
}
