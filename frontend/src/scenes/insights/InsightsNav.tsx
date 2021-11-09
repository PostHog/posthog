import { Button, Row, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { isMobile } from 'lib/utils'
import React from 'react'
import { HotKeys, ViewType } from '~/types'
import { insightLogic } from './insightLogic'
import { ClockCircleOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const { TabPane } = Tabs

function InsightHotkey({ hotkey }: { hotkey: HotKeys }): JSX.Element {
    return !isMobile() ? <span className="hotkey">{hotkey}</span> : <></>
}

export function InsightsNav(): JSX.Element {
    const { activeView } = useValues(insightLogic)
    const { setActiveView } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <Row justify="space-between" align="middle" className="top-bar">
            <Tabs
                activeKey={activeView}
                style={{
                    overflow: 'visible',
                }}
                className="top-bar"
                onChange={(key) => setActiveView(key as ViewType)}
                animated={false}
                tabBarExtraContent={
                    featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS]
                        ? undefined
                        : {
                              right: (
                                  <Button
                                      type="link"
                                      data-attr="insight-history-button"
                                      className={`insight-history-button${
                                          (activeView as ViewType) === ViewType.HISTORY ? ' active' : ''
                                      }`}
                                      onClick={() => setActiveView(ViewType.HISTORY)}
                                      icon={<ClockCircleOutlined />}
                                  >
                                      History
                                  </Button>
                              ),
                          }
                }
            >
                <TabPane
                    tab={
                        <span data-attr="insight-trends-tab">
                            Trends
                            <InsightHotkey hotkey="t" />
                        </span>
                    }
                    key={ViewType.TRENDS}
                />
                <TabPane
                    tab={
                        <span data-attr="insight-funnels-tab">
                            Funnels
                            <InsightHotkey hotkey="f" />
                        </span>
                    }
                    key={ViewType.FUNNELS}
                />
                <TabPane
                    tab={
                        <span data-attr="insight-retention-tab">
                            Retention
                            <InsightHotkey hotkey="r" />
                        </span>
                    }
                    key={ViewType.RETENTION}
                />
                <TabPane
                    tab={
                        <span data-attr="insight-path-tab">
                            User Paths
                            <InsightHotkey hotkey="p" />
                        </span>
                    }
                    key={ViewType.PATHS}
                />
                <TabPane
                    tab={
                        <Tooltip
                            placement="top"
                            title="View average and distribution of session durations."
                            data-attr="insight-sessions-tab"
                        >
                            Sessions
                            <InsightHotkey hotkey="o" />
                        </Tooltip>
                    }
                    key={ViewType.SESSIONS}
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
                                        Example: If a user performed an action on Monday and again on Friday, it would
                                        be shown as "2 days".
                                    </i>
                                </>
                            }
                            data-attr="insight-stickiness-tab"
                        >
                            Stickiness
                            <InsightHotkey hotkey="i" />
                        </Tooltip>
                    }
                    key={ViewType.STICKINESS}
                />
                <TabPane
                    tab={
                        <Tooltip
                            placement="top"
                            title={
                                <>Understand growth by breaking down new, resurrected, returning, and dormant users.</>
                            }
                            data-attr="insight-lifecycle-tab"
                        >
                            Lifecycle
                            <InsightHotkey hotkey="l" />
                        </Tooltip>
                    }
                    key={ViewType.LIFECYCLE}
                />
            </Tabs>
        </Row>
    )
}
