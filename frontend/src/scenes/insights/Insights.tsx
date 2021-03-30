import React, { useState } from 'react'
import { useActions, useMountedLogic, useValues, BindLogic } from 'kea'

import { isMobile, Loading } from 'lib/utils'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { DateFilter } from './DateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter/IntervalFilter'

import { PageHeader } from 'lib/components/PageHeader'

import { ChartFilter } from 'lib/components/ChartFilter'
import { Tabs, Row, Col, Card, Button, Tooltip } from 'antd'
import {
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    ACTIONS_TABLE,
    ACTIONS_PIE_CHART,
    ACTIONS_BAR_CHART_VALUE,
    FUNNEL_VIZ,
    ShownAsValue,
} from 'lib/constants'
import { annotationsLogic } from '~/lib/components/Annotations'
import { router } from 'kea-router'

import { RetentionContainer } from 'scenes/retention/RetentionContainer'

import { Paths } from 'scenes/paths/Paths'

import { RetentionTab, SessionTab, TrendTab, PathTab, FunnelTab } from './InsightTabs'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic, logicFromInsight, ViewType } from './insightLogic'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { InsightHistoryPanel } from './InsightHistoryPanel'
import { SavedFunnels } from './SavedCard'
import { ReloadOutlined } from '@ant-design/icons'
import { insightCommandLogic } from './insightCommandLogic'

import './Insights.scss'
import { ErrorMessage, TimeOut } from './EmptyStates'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { People } from 'scenes/funnels/People'
import { TrendLegend } from './TrendLegend'
import { TrendInsight } from 'scenes/trends/Trends'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { TZIndicator } from 'lib/components/TimezoneAware'
import { DisplayType, FilterType, HotKeys } from '~/types'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

dayjs.extend(relativeTime)
const { TabPane } = Tabs

const showIntervalFilter = function (activeView: ViewType, filter: FilterType): boolean {
    switch (activeView) {
        case ViewType.FUNNELS:
            return filter.display === ACTIONS_LINE_GRAPH_LINEAR
        case ViewType.RETENTION:
        case ViewType.PATHS:
            return false
        case ViewType.TRENDS:
        case ViewType.STICKINESS:
        case ViewType.LIFECYCLE:
        case ViewType.SESSIONS:
        default:
            return ![ACTIONS_PIE_CHART, ACTIONS_TABLE, ACTIONS_BAR_CHART_VALUE].includes(filter.display || '') // sometimes insights aren't set for trends
    }
}

const showChartFilter = function (activeView: ViewType, featureFlags: Record<string, boolean>): boolean {
    switch (activeView) {
        case ViewType.TRENDS:
        case ViewType.STICKINESS:
        case ViewType.SESSIONS:
        case ViewType.RETENTION:
            return true
        case ViewType.FUNNELS:
            return featureFlags['funnel-trends-1269']
        case ViewType.LIFECYCLE:
        case ViewType.PATHS:
            return false
        default:
            return true // sometimes insights aren't set for trends
    }
}

const showDateFilter = {
    [`${ViewType.TRENDS}`]: true,
    [`${ViewType.STICKINESS}`]: true,
    [`${ViewType.LIFECYCLE}`]: true,
    [`${ViewType.SESSIONS}`]: true,
    [`${ViewType.FUNNELS}`]: true,
    [`${ViewType.RETENTION}`]: false,
    [`${ViewType.PATHS}`]: true,
}

const showComparePrevious = {
    [`${ViewType.TRENDS}`]: true,
    [`${ViewType.STICKINESS}`]: true,
    [`${ViewType.LIFECYCLE}`]: false,
    [`${ViewType.SESSIONS}`]: true,
    [`${ViewType.FUNNELS}`]: false,
    [`${ViewType.RETENTION}`]: false,
    [`${ViewType.PATHS}`]: false,
}

function InsightHotkey({ hotkey }: { hotkey: HotKeys }): JSX.Element {
    /* Temporary element to only show hotkeys when feature flag is active */
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags['hotkeys-3740'] && !isMobile() ? <span className="hotkey">{hotkey}</span> : <></>
}

export function Insights(): JSX.Element {
    useMountedLogic(insightCommandLogic)
    const [{ fromItem }] = useState(router.values.hashParams)
    const { clearAnnotationsToCreate } = useActions(annotationsLogic({ pageKey: fromItem }))
    const { annotationsToCreate } = useValues(annotationsLogic({ pageKey: fromItem }))
    const { lastRefresh, isLoading, activeView, allFilters, showTimeoutMessage, showErrorMessage } = useValues(
        insightLogic
    )
    const { setActiveView } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { reportHotkeyNavigation } = useActions(eventUsageLogic)

    const { loadResults } = useActions(logicFromInsight(activeView, { dashboardItemId: null, filters: allFilters }))
    const dateFilterDisabled = activeView === ViewType.FUNNELS && isFunnelEmpty(allFilters)

    const handleHotkeyNavigation = (view: ViewType, hotkey: HotKeys): void => {
        setActiveView(view)
        reportHotkeyNavigation('insights', hotkey)
    }

    useKeyboardHotkeys(
        featureFlags['hotkeys-3740']
            ? {
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
                      disabled: !featureFlags['remove-shownas'],
                  },
                  l: {
                      action: () => handleHotkeyNavigation(ViewType.LIFECYCLE, 'l'),
                      disabled: !featureFlags['remove-shownas'],
                  },
              }
            : {}
    )

    return (
        <div className="insights-page">
            <PageHeader title="Insights" />
            <Row justify="space-between" align="middle" className="top-bar">
                <Tabs
                    size="large"
                    activeKey={activeView}
                    style={{
                        overflow: 'visible',
                    }}
                    className="top-bar"
                    onChange={(key) => setActiveView(key)}
                    animated={false}
                    tabBarExtraContent={{
                        right: (
                            <Button
                                type={activeView === 'history' ? 'primary' : undefined}
                                data-attr="insight-history-button"
                                onClick={() => setActiveView('history')}
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
                    {featureFlags['remove-shownas'] && (
                        <TabPane
                            tab={
                                <Tooltip
                                    placement="bottom"
                                    title={
                                        <>
                                            Stickiness shows you how many days users performed an action within the
                                            timeframe.
                                            <br />
                                            <br />
                                            If a user performed an action on Monday and again on Friday, it would be
                                            shown as "2 days".
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
                    )}
                    {featureFlags['remove-shownas'] && (
                        <TabPane
                            tab={
                                <Tooltip
                                    placement="bottom"
                                    title={
                                        <>
                                            Lifecycle will show you new, resurrected, returning and dormant users so you
                                            know how your user bases is growing.
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
                    )}
                </Tabs>
            </Row>
            <Row gutter={16}>
                {activeView === 'history' ? (
                    <Col xs={24} xl={24}>
                        <Card className="" style={{ overflow: 'visible' }}>
                            <InsightHistoryPanel />
                        </Card>
                    </Col>
                ) : (
                    <>
                        <Col xs={24} xl={7}>
                            <Card className="" style={{ overflow: 'visible' }}>
                                <div>
                                    {/*
                                These are insight specific filters.
                                They each have insight specific logics
                                */}
                                    {featureFlags['remove-shownas']
                                        ? {
                                              [`${ViewType.TRENDS}`]: <TrendTab view={ViewType.TRENDS} />,
                                              [`${ViewType.STICKINESS}`]: <TrendTab view={ViewType.STICKINESS} />,
                                              [`${ViewType.LIFECYCLE}`]: <TrendTab view={ViewType.LIFECYCLE} />,
                                              [`${ViewType.SESSIONS}`]: <SessionTab />,
                                              [`${ViewType.FUNNELS}`]: <FunnelTab />,
                                              [`${ViewType.RETENTION}`]: <RetentionTab />,
                                              [`${ViewType.PATHS}`]: <PathTab />,
                                          }[activeView]
                                        : {
                                              [`${ViewType.TRENDS}`]: <TrendTab view={ViewType.TRENDS} />,
                                              [`${ViewType.SESSIONS}`]: <SessionTab />,
                                              [`${ViewType.FUNNELS}`]: <FunnelTab />,
                                              [`${ViewType.RETENTION}`]: <RetentionTab />,
                                              [`${ViewType.PATHS}`]: <PathTab />,
                                          }[activeView]}
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
                        <Col xs={24} xl={17}>
                            {/*
                        These are filters that are reused between insight features.
                        They each have generic logic that updates the url
                        */}
                            <Card
                                title={
                                    <div style={{ display: 'flex', alignItems: 'center' }}>
                                        <TZIndicator style={{ float: 'left' }} />
                                        <div style={{ width: '100%', textAlign: 'right' }}>
                                            {showIntervalFilter(activeView, allFilters) && (
                                                <IntervalFilter view={activeView} />
                                            )}
                                            {showChartFilter(activeView, featureFlags) && (
                                                <ChartFilter
                                                    onChange={(display: DisplayType) => {
                                                        if (
                                                            display === ACTIONS_TABLE ||
                                                            display === ACTIONS_PIE_CHART
                                                        ) {
                                                            clearAnnotationsToCreate()
                                                        }
                                                    }}
                                                    filters={allFilters}
                                                    disabled={allFilters.shown_as === ShownAsValue.LIFECYCLE}
                                                />
                                            )}

                                            {showDateFilter[activeView] && (
                                                <DateFilter
                                                    defaultValue="Last 7 days"
                                                    disabled={dateFilterDisabled}
                                                    bordered={false}
                                                />
                                            )}

                                            {showComparePrevious[activeView] && <CompareFilter />}
                                            <SaveToDashboard
                                                item={{
                                                    entity: {
                                                        filters: allFilters,
                                                        annotations: annotationsToCreate,
                                                    },
                                                }}
                                            />
                                        </div>
                                    </div>
                                }
                                headStyle={{ backgroundColor: 'rgba(0,0,0,.03)' }}
                                data-attr="insights-graph"
                            >
                                <div>
                                    {lastRefresh && (
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
                                        ) : featureFlags['remove-shownas'] ? (
                                            {
                                                [`${ViewType.TRENDS}`]: <TrendInsight view={ViewType.TRENDS} />,
                                                [`${ViewType.STICKINESS}`]: <TrendInsight view={ViewType.STICKINESS} />,
                                                [`${ViewType.LIFECYCLE}`]: <TrendInsight view={ViewType.LIFECYCLE} />,
                                                [`${ViewType.SESSIONS}`]: <TrendInsight view={ViewType.SESSIONS} />,
                                                [`${ViewType.FUNNELS}`]: <FunnelInsight />,
                                                [`${ViewType.RETENTION}`]: <RetentionContainer />,
                                                [`${ViewType.PATHS}`]: <Paths />,
                                            }[activeView]
                                        ) : (
                                            {
                                                [`${ViewType.TRENDS}`]: <TrendInsight view={ViewType.TRENDS} />,
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
                                    <Card>
                                        <FunnelPeople />
                                    </Card>
                                )}
                            {featureFlags['trend-legend'] &&
                                (!allFilters.display ||
                                    allFilters.display === ACTIONS_LINE_GRAPH_LINEAR ||
                                    allFilters.display === ACTIONS_LINE_GRAPH_CUMULATIVE) &&
                                (activeView === ViewType.TRENDS || activeView === ViewType.SESSIONS) && (
                                    <Card>
                                        <BindLogic
                                            logic={trendsLogic}
                                            props={{ dashboardItemId: null, view: activeView }}
                                        >
                                            <TrendLegend />
                                        </BindLogic>
                                    </Card>
                                )}
                        </Col>
                    </>
                )}
            </Row>
        </div>
    )
}

const isFunnelEmpty = (filters: FilterType): boolean => {
    return (!filters.actions && !filters.events) || (filters.actions?.length === 0 && filters.events?.length === 0)
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
