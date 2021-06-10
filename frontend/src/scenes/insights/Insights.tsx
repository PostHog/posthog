import React, { useState } from 'react'
import { useActions, useMountedLogic, useValues, BindLogic } from 'kea'

import { isMobile, Loading } from 'lib/utils'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

import { Tabs, Row, Col, Card, Button, Tooltip } from 'antd'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_LINE_GRAPH_CUMULATIVE, FUNNEL_VIZ, FEATURE_FLAGS } from 'lib/constants'
import { annotationsLogic } from '~/lib/components/Annotations'
import { router } from 'kea-router'

import { RetentionContainer } from 'scenes/retention/RetentionContainer'

import { Paths } from 'scenes/paths/Paths'

import { RetentionTab, SessionTab, TrendTab, PathTab, FunnelTab } from './InsightTabs'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic, logicFromInsight, ViewType } from './insightLogic'
import { InsightHistoryPanel } from './InsightHistoryPanel'
import { SavedFunnels } from './SavedCard'
import { ReloadOutlined, DownOutlined, UpOutlined } from '@ant-design/icons'
import { insightCommandLogic } from './insightCommandLogic'

import './Insights.scss'
import { ErrorMessage, TimeOut } from './EmptyStates'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { People } from 'scenes/funnels/People'
import { InsightsTable } from './InsightsTable'
import { TrendInsight } from 'scenes/trends/Trends'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { HotKeys } from '~/types'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { InsightDisplayConfig } from './InsightTabs/InsightDisplayConfig'
import { PageHeader } from 'lib/components/PageHeader'
import { NPSPrompt } from 'lib/experimental/NPSPrompt'

export interface BaseTabProps {
    annotationsToCreate: any[] // TODO: Type properly
}

dayjs.extend(relativeTime)
const { TabPane } = Tabs

function InsightHotkey({ hotkey }: { hotkey: HotKeys }): JSX.Element {
    return !isMobile() ? <span className="hotkey">{hotkey}</span> : <></>
}

export function Insights(): JSX.Element {
    useMountedLogic(insightCommandLogic)
    const [{ fromItem }] = useState(router.values.hashParams)
    const { clearAnnotationsToCreate } = useActions(annotationsLogic({ pageKey: fromItem }))
    const { annotationsToCreate } = useValues(annotationsLogic({ pageKey: fromItem }))
    const {
        lastRefresh,
        isLoading,
        activeView,
        allFilters,
        showTimeoutMessage,
        showErrorMessage,
        controlsCollapsed,
    } = useValues(insightLogic)
    const { setActiveView, toggleControlsCollapsed } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { reportHotkeyNavigation } = useActions(eventUsageLogic)

    const { loadResults } = useActions(logicFromInsight(activeView, { dashboardItemId: null, filters: allFilters }))

    const newUI = featureFlags[FEATURE_FLAGS.QUERY_UX_V2]
    const horizontalUI = newUI && activeView !== ViewType.FUNNELS

    const handleHotkeyNavigation = (view: ViewType, hotkey: HotKeys): void => {
        setActiveView(view)
        reportHotkeyNavigation('insights', hotkey)
    }

    useKeyboardHotkeys({
        t: {
            action: () => handleHotkeyNavigation(ViewType.TRENDS, 't'),
        },
        f: {
            action: () => handleHotkeyNavigation(ViewType.FUNNELS, 'f'),
        },
        s: {
            action: () => handleHotkeyNavigation(ViewType.SESSIONS, 's'),
        },
        r: {
            action: () => handleHotkeyNavigation(ViewType.RETENTION, 'r'),
        },
        p: {
            action: () => handleHotkeyNavigation(ViewType.PATHS, 'p'),
        },
        k: {
            action: () => handleHotkeyNavigation(ViewType.STICKINESS, 'k'),
        },
        l: {
            action: () => handleHotkeyNavigation(ViewType.LIFECYCLE, 'l'),
        },
    })

    return (
        <div className={`insights-page${horizontalUI ? ' horizontal-ui' : ''}`}>
            <PageHeader title="Insights" />
            <Row justify="space-between" align="middle" className="top-bar">
                <Tabs
                    activeKey={activeView}
                    style={{
                        overflow: 'visible',
                    }}
                    className="top-bar"
                    onChange={(key) => setActiveView(key as ViewType)}
                    animated={false}
                    tabBarExtraContent={{
                        right: (
                            <Button
                                type={activeView === ViewType.HISTORY ? 'primary' : undefined}
                                data-attr="insight-history-button"
                                onClick={() => setActiveView(ViewType.HISTORY)}
                            >
                                History
                            </Button>
                        ),
                    }}
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
                            <span data-attr="insight-sessions-tab">
                                Sessions
                                <InsightHotkey hotkey="s" />
                            </span>
                        }
                        key={ViewType.SESSIONS}
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
                                placement="bottom"
                                title={
                                    <>
                                        Stickiness shows you how many days users performed an action repeteadely within
                                        a timeframe.
                                        <br />
                                        <br />
                                        <i>
                                            Example: If a user performed an action on Monday and again on Friday, it
                                            would be shown as "2 days".
                                        </i>
                                    </>
                                }
                                data-attr="insight-stickiness-tab"
                            >
                                Stickiness
                                <InsightHotkey hotkey="k" />
                            </Tooltip>
                        }
                        key={ViewType.STICKINESS}
                    />
                    <TabPane
                        tab={
                            <Tooltip
                                placement="bottom"
                                title={
                                    <>
                                        Lifecycle will show you new, resurrected, returning and dormant users so you
                                        understand how your user base is composed. This can help you understand where
                                        your user growth is coming from.
                                    </>
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
            <Row gutter={16}>
                {activeView === ViewType.HISTORY ? (
                    <Col xs={24} xl={24}>
                        <Card className="" style={{ overflow: 'visible' }}>
                            <InsightHistoryPanel />
                        </Card>
                    </Col>
                ) : (
                    <>
                        <Col xs={24} xl={horizontalUI ? 24 : 7}>
                            <Card
                                className={`insight-controls${controlsCollapsed ? ' collapsed' : ''}`}
                                onClick={() => controlsCollapsed && toggleControlsCollapsed()}
                            >
                                {horizontalUI && (
                                    <>
                                        <div
                                            role="button"
                                            title={controlsCollapsed ? 'Expand panel' : 'Collapse panel'}
                                            className="collapse-control"
                                            onClick={() => !controlsCollapsed && toggleControlsCollapsed()}
                                        >
                                            {controlsCollapsed ? <DownOutlined /> : <UpOutlined />}
                                        </div>
                                        {controlsCollapsed && (
                                            <div>
                                                <h3 className="l3">Query definition</h3>
                                                <span className="text-small text-muted">
                                                    Click here to view and change the query events, filters and other
                                                    settings.
                                                </span>
                                            </div>
                                        )}
                                    </>
                                )}
                                <div className="tabs-inner">
                                    {/* These are insight specific filters. They each have insight specific logics */}
                                    {
                                        {
                                            [`${ViewType.TRENDS}`]: (
                                                <TrendTab
                                                    view={ViewType.TRENDS}
                                                    annotationsToCreate={annotationsToCreate}
                                                />
                                            ),
                                            [`${ViewType.STICKINESS}`]: (
                                                <TrendTab
                                                    view={ViewType.STICKINESS}
                                                    annotationsToCreate={annotationsToCreate}
                                                />
                                            ),
                                            [`${ViewType.LIFECYCLE}`]: (
                                                <TrendTab
                                                    view={ViewType.LIFECYCLE}
                                                    annotationsToCreate={annotationsToCreate}
                                                />
                                            ),
                                            [`${ViewType.SESSIONS}`]: (
                                                <SessionTab annotationsToCreate={annotationsToCreate} />
                                            ),
                                            [`${ViewType.FUNNELS}`]: (
                                                <FunnelTab annotationsToCreate={annotationsToCreate} newUI={newUI} />
                                            ),
                                            [`${ViewType.RETENTION}`]: (
                                                <RetentionTab annotationsToCreate={annotationsToCreate} />
                                            ),
                                            [`${ViewType.PATHS}`]: (
                                                <PathTab annotationsToCreate={annotationsToCreate} />
                                            ),
                                        }[activeView]
                                    }
                                </div>
                            </Card>
                            {activeView === ViewType.FUNNELS && (
                                <Card
                                    title={<Row align="middle">Funnels Saved in Project</Row>}
                                    style={{ marginTop: 16 }}
                                >
                                    <SavedFunnels />
                                </Card>
                            )}
                        </Col>
                        <Col xs={24} xl={horizontalUI ? 24 : 17}>
                            {/* TODO: extract to own file. Props: activeView, allFilters, showDateFilter, dateFilterDisabled, annotationsToCreate; lastRefresh, showErrorMessage, showTimeoutMessage, isLoading; ... */}
                            {/* These are filters that are reused between insight features. They
                                each have generic logic that updates the url
                            */}
                            <Card
                                title={
                                    <InsightDisplayConfig
                                        activeView={activeView}
                                        allFilters={allFilters}
                                        annotationsToCreate={annotationsToCreate}
                                        clearAnnotationsToCreate={clearAnnotationsToCreate}
                                        horizontalUI={horizontalUI}
                                    />
                                }
                                data-attr="insights-graph"
                                className="insights-graph-container"
                            >
                                <div>
                                    {lastRefresh && dayjs().subtract(3, 'minutes') > dayjs(lastRefresh) && (
                                        <small style={{ position: 'absolute', marginTop: -21, right: 24 }}>
                                            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
                                            <Button
                                                size="small"
                                                type="link"
                                                onClick={() => loadResults(true)}
                                                style={{ margin: 0 }}
                                            >
                                                refresh
                                                <ReloadOutlined
                                                    style={{ cursor: 'pointer', marginTop: -3, marginLeft: 3 }}
                                                />
                                            </Button>
                                        </small>
                                    )}
                                    {showErrorMessage ? (
                                        <ErrorMessage />
                                    ) : (
                                        showTimeoutMessage && <TimeOut isLoading={isLoading} />
                                    )}
                                    <div
                                        style={{
                                            display: showErrorMessage || showTimeoutMessage ? 'none' : 'block',
                                        }}
                                    >
                                        {showErrorMessage ? (
                                            <ErrorMessage />
                                        ) : showTimeoutMessage ? (
                                            <TimeOut isLoading={isLoading} />
                                        ) : (
                                            {
                                                [`${ViewType.TRENDS}`]: <TrendInsight view={ViewType.TRENDS} />,
                                                [`${ViewType.STICKINESS}`]: <TrendInsight view={ViewType.STICKINESS} />,
                                                [`${ViewType.LIFECYCLE}`]: <TrendInsight view={ViewType.LIFECYCLE} />,
                                                [`${ViewType.SESSIONS}`]: <TrendInsight view={ViewType.SESSIONS} />,
                                                [`${ViewType.FUNNELS}`]: <FunnelInsight />,
                                                [`${ViewType.RETENTION}`]: <RetentionContainer />,
                                                [`${ViewType.PATHS}`]: <Paths />,
                                            }[activeView]
                                        )}
                                    </div>
                                </div>
                            </Card>
                            {!showErrorMessage &&
                                !showTimeoutMessage &&
                                activeView === ViewType.FUNNELS &&
                                allFilters.display === FUNNEL_VIZ && (
                                    <Card style={{ marginTop: 16 }}>
                                        <FunnelPeople />
                                    </Card>
                                )}
                            {(!allFilters.display ||
                                allFilters.display === ACTIONS_LINE_GRAPH_LINEAR ||
                                allFilters.display === ACTIONS_LINE_GRAPH_CUMULATIVE) &&
                                (activeView === ViewType.TRENDS || activeView === ViewType.SESSIONS) && (
                                    <Card style={{ marginTop: 16 }}>
                                        <BindLogic
                                            logic={trendsLogic}
                                            props={{ dashboardItemId: null, view: activeView }}
                                        >
                                            <InsightsTable showTotalCount={activeView !== ViewType.SESSIONS} />
                                        </BindLogic>
                                    </Card>
                                )}
                        </Col>
                    </>
                )}
            </Row>
            <NPSPrompt />
        </div>
    )
}

function FunnelInsight(): JSX.Element {
    const { stepsWithCount, isValidFunnel, stepsWithCountLoading } = useValues(funnelLogic({}))

    return (
        <div style={{ height: 300, position: 'relative' }}>
            {stepsWithCountLoading && <Loading />}
            {isValidFunnel ? (
                <FunnelViz steps={stepsWithCount} />
            ) : (
                !stepsWithCountLoading && (
                    <div
                        style={{
                            textAlign: 'center',
                        }}
                    >
                        <span>
                            Enter the details to your funnel and click 'calculate' to create a funnel visualization
                        </span>
                    </div>
                )
            )}
        </div>
    )
}

function FunnelPeople(): JSX.Element {
    const { stepsWithCount } = useValues(funnelLogic())
    if (stepsWithCount && stepsWithCount.length > 0) {
        return <People />
    }
    return <></>
}
