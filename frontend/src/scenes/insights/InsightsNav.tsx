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
                        <Tooltip
                            placement="top"
                            title={INSIGHT_TYPES_METADATA[InsightType.TRENDS].description}
                            data-attr="insight-trends-tab"
                        >
                            Trends
                            <InsightHotkey hotkey="t" />
                        </Tooltip>
                    }
                    key={InsightType.TRENDS}
                />
                <TabPane
                    tab={
                        <Tooltip
                            placement="top"
                            title={INSIGHT_TYPES_METADATA[InsightType.FUNNELS].description}
                            data-attr="insight-funnels-tab"
                            ref={funnelTab}
                        >
                            Funnels
                            <InsightHotkey hotkey="f" />
                        </Tooltip>
                    }
                    key={InsightType.FUNNELS}
                />
                <TabPane
                    tab={
                        <Tooltip
                            placement="top"
                            title={INSIGHT_TYPES_METADATA[InsightType.RETENTION].description}
                            data-attr="insight-retention-tab"
                        >
                            Retention
                            <InsightHotkey hotkey="r" />
                        </Tooltip>
                    }
                    key={InsightType.RETENTION}
                />
                <TabPane
                    tab={
                        <Tooltip
                            placement="top"
                            title={INSIGHT_TYPES_METADATA[InsightType.PATHS].description}
                            data-attr="insight-path-tab"
                        >
                            User Paths
                            <InsightHotkey hotkey="p" />
                        </Tooltip>
                    }
                    key={InsightType.PATHS}
                />
                <TabPane
                    tab={
                        <Tooltip
                            placement="top"
                            title={INSIGHT_TYPES_METADATA[InsightType.STICKINESS].description}
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
                            title={INSIGHT_TYPES_METADATA[InsightType.LIFECYCLE].description}
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
                            title={INSIGHT_TYPES_METADATA[InsightType.SESSIONS].description}
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
        </>
    )
}
