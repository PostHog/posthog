import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconBolt, IconPerson, IconShare } from '@posthog/icons'

import { LiveUserCount } from 'lib/components/LiveUserCount'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Popover } from 'lib/lemon-ui/Popover'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { teamLogic } from 'scenes/teamLogic'
import { shareNudgeLogic } from 'scenes/web-analytics/shareNudgeLogic'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebAnalyticsMenu } from 'scenes/web-analytics/WebAnalyticsMenu'

export function WebAnalyticsHeaderButtons(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { shouldFilterTestAccounts } = useValues(webAnalyticsLogic)
    const { setShouldFilterTestAccounts } = useActions(webAnalyticsLogic)
    const { emphasizeShareButton } = useValues(shareNudgeLogic)
    const [showPopover, setShowPopover] = useState(false)

    const hasFeatureFlag = featureFlags[FEATURE_FLAGS.SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES]
    const isUsingNewEngine = currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables
    const showLiveUserCount =
        featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] || featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR]
    const showShareButton =
        !featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] && !featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR]

    const handleShare = (): void => {
        void copyToClipboard(window.location.href, 'link')
        posthog.capture('web analytics share link copied', { source: 'header_button' })
    }

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
            {showLiveUserCount && (
                <LiveUserCount
                    docLink="https://posthog.com/docs/web-analytics/faq#i-am-online-but-the-online-user-count-is-not-reflecting-my-user"
                    dataAttr="web-analytics-live-user-count"
                />
            )}
            {showShareButton && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={emphasizeShareButton ? <IconShare fontSize="16" /> : <IconLink fontSize="16" />}
                    tooltip={emphasizeShareButton ? undefined : 'Share'}
                    tooltipPlacement="top"
                    onClick={handleShare}
                    data-attr="web-analytics-share-button"
                >
                    {emphasizeShareButton ? 'Share' : undefined}
                </LemonButton>
            )}
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPerson />}
                tooltip="Filter out internal and test users"
                tooltipPlacement="top"
                onClick={() => setShouldFilterTestAccounts(!shouldFilterTestAccounts)}
                data-attr="web-analytics-filter-test-accounts"
            >
                Filter test accounts <LemonSwitch checked={shouldFilterTestAccounts} className="ml-1" />
            </LemonButton>
            {hasFeatureFlag && (
                <Popover
                    visible={showPopover}
                    onClickOutside={() => setShowPopover(false)}
                    overlay={
                        <div className="p-4 max-w-160">
                            <h3 className="font-semibold mb-2">About the new query engine</h3>
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
                        className="flex items-center gap-2 cursor-pointer h-[33px] mx-1"
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
