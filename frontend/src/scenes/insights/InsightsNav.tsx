import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { isMobile } from 'lib/utils'
import React, { useRef } from 'react'
import { HotKeys, InsightType } from '~/types'
import { insightLogic } from './insightLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import clsx from 'clsx'
import { FunnelsCue } from './InsightTabs/TrendTab/FunnelsCue'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

const { TabPane } = Tabs

function InsightHotkey({ hotkey }: { hotkey: HotKeys }): JSX.Element {
    return !isMobile() ? <span className="hotkey">{hotkey}</span> : <></>
}

export function InsightsNav(): JSX.Element {
    const { activeView, insightProps } = useValues(insightLogic)
    const { setActiveView } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const funnelTab = useRef<HTMLSpanElement>(null)

    return (
        <>
            <FunnelsCue
                props={insightProps}
                tooltipPosition={
                    // 1.5x because it's 2 tabs (trends & funnels) + margin between tabs
                    funnelTab?.current ? funnelTab.current.getBoundingClientRect().width * 1.5 + 16 : undefined
                }
            />
            <Tabs
                activeKey={activeView}
                className="top-bar"
                onChange={(key) => setActiveView(key as InsightType)}
                animated={false}
            >
                <TabPane
                    tab={
                        <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[InsightType.TRENDS].description}>
                            <span data-attr="insight-trends-tab">
                                Trends
                                <InsightHotkey hotkey="t" />
                            </span>
                        </Tooltip>
                    }
                    key={InsightType.TRENDS}
                />
                <TabPane
                    tab={
                        <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[InsightType.FUNNELS].description}>
                            <span data-attr="insight-funnels-tab" ref={funnelTab}>
                                Funnels
                                <InsightHotkey hotkey="f" />
                            </span>
                        </Tooltip>
                    }
                    key={InsightType.FUNNELS}
                />
                <TabPane
                    tab={
                        <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[InsightType.RETENTION].description}>
                            <span data-attr="insight-retention-tab">
                                Retention
                                <InsightHotkey hotkey="r" />
                            </span>
                        </Tooltip>
                    }
                    key={InsightType.RETENTION}
                />
                <TabPane
                    tab={
                        <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[InsightType.PATHS].description}>
                            <span data-attr="insight-paths-tab">
                                User Paths
                                <InsightHotkey hotkey="p" />
                            </span>
                        </Tooltip>
                    }
                    key={InsightType.PATHS}
                />
                <TabPane
                    tab={
                        <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[InsightType.STICKINESS].description}>
                            <span data-attr="insight-stickiness-tab">
                                Stickiness
                                <InsightHotkey hotkey="i" />
                            </span>
                        </Tooltip>
                    }
                    key={InsightType.STICKINESS}
                />
                <TabPane
                    tab={
                        <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[InsightType.LIFECYCLE].description}>
                            <span data-attr="insight-lifecycle-tab">
                                Lifecycle
                                <InsightHotkey hotkey="l" />
                            </span>
                        </Tooltip>
                    }
                    key={InsightType.LIFECYCLE}
                />
                <TabPane
                    tab={
                        <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[InsightType.SESSIONS].description}>
                            <div
                                className={clsx(featureFlags[FEATURE_FLAGS.SESSION_INSIGHT_REMOVAL] && 'deprecated')}
                                data-attr="insight-sessions-tab"
                            >
                                Sessions
                                <InsightHotkey hotkey="o" />
                            </div>
                        </Tooltip>
                    }
                    key={InsightType.SESSIONS}
                />
            </Tabs>
        </>
    )
}
