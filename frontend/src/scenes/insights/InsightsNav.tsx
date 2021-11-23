import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { isMobile } from 'lib/utils'
import React from 'react'
import { HotKeys, InsightType } from '~/types'
import { insightLogic } from './insightLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import clsx from 'clsx'

const { TabPane } = Tabs

function InsightHotkey({ hotkey }: { hotkey: HotKeys }): JSX.Element {
    return !isMobile() ? <span className="hotkey">{hotkey}</span> : <></>
}

export function InsightsNav(): JSX.Element {
    const { activeView } = useValues(insightLogic)
    const { setActiveView } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <Tabs
            activeKey={activeView}
            className="top-bar"
            onChange={(key) => setActiveView(key as InsightType)}
            animated={false}
        >
            <TabPane
                tab={
                    <span data-attr="insight-trends-tab">
                        Trends
                        <InsightHotkey hotkey="t" />
                    </span>
                }
                key={InsightType.TRENDS}
            />
            <TabPane
                tab={
                    <span data-attr="insight-funnels-tab">
                        Funnels
                        <InsightHotkey hotkey="f" />
                    </span>
                }
                key={InsightType.FUNNELS}
            />
            <TabPane
                tab={
                    <span data-attr="insight-retention-tab">
                        Retention
                        <InsightHotkey hotkey="r" />
                    </span>
                }
                key={InsightType.RETENTION}
            />
            <TabPane
                tab={
                    <span data-attr="insight-path-tab">
                        User Paths
                        <InsightHotkey hotkey="p" />
                    </span>
                }
                key={InsightType.PATHS}
            />
            <TabPane
                tab={
                    <Tooltip
                        placement="top"
                        title={
                            <>
                                Stickiness shows you how many days users performed an action repeatedly within a
                                timeframe.
                                <br />
                                <br />
                                <i>
                                    Example: If a user performed an action on Monday and again on Friday, it would be
                                    shown as "2 days".
                                </i>
                            </>
                        }
                        data-attr="insight-stickiness-tab"
                    >
                        Stickiness
                        <InsightHotkey hotkey="i" />
                    </Tooltip>
                }
                key={InsightType.STICKINESS}
            />
            <TabPane
                tab={
                    <Tooltip
                        placement="top"
                        title={<>Understand growth by breaking down new, resurrected, returning, and dormant users.</>}
                        data-attr="insight-lifecycle-tab"
                    >
                        Lifecycle
                        <InsightHotkey hotkey="l" />
                    </Tooltip>
                }
                key={InsightType.LIFECYCLE}
            />
            <TabPane
                tab={
                    <Tooltip
                        placement="top"
                        title="View average and distribution of session durations."
                        data-attr="insight-sessions-tab"
                    >
                        <div className={clsx(featureFlags[FEATURE_FLAGS.SESSION_INSIGHT_REMOVAL] && 'deprecated')}>
                            Sessions
                            <InsightHotkey hotkey="o" />
                        </div>
                    </Tooltip>
                }
                key={InsightType.SESSIONS}
            />
        </Tabs>
    )
}
