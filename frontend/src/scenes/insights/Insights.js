import React, { useState } from 'react'
import { useActions, useMountedLogic, useValues } from 'kea'

import { Loading } from 'lib/utils'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import moment from 'moment'
import { DateFilter } from 'lib/components/DateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter/IntervalFilter'

import { PageHeader } from 'lib/components/PageHeader'

import { ChartFilter } from 'lib/components/ChartFilter'
import { Tabs, Row, Col, Card, Button } from 'antd'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_TABLE, ACTIONS_PIE_CHART, LIFECYCLE, FUNNEL_VIZ } from 'lib/constants'
import { hot } from 'react-hot-loader/root'
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
import { TrendInsight } from 'scenes/trends/Trends'

const { TabPane } = Tabs

const showIntervalFilter = function (activeView, filter) {
    switch (activeView) {
        case ViewType.TRENDS:
        case ViewType.STICKINESS:
        case ViewType.LIFECYCLE:
        case ViewType.SESSIONS:
            return true
        case ViewType.FUNNELS:
            return filter.display === ACTIONS_LINE_GRAPH_LINEAR
        case ViewType.RETENTION:
        case ViewType.PATHS:
            return false
        default:
            return true // sometimes insights aren't set for trends
    }
}

const showChartFilter = function (activeView, featureFlags) {
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

export const Insights = hot(_Insights)
function _Insights() {
    useMountedLogic(insightCommandLogic)
    const [{ fromItem }] = useState(router.values.hashParams)
    const { clearAnnotationsToCreate } = useActions(annotationsLogic({ pageKey: fromItem }))
    const { annotationsToCreate } = useValues(annotationsLogic({ pageKey: fromItem }))
    const { lastRefresh, isLoading, activeView, allFilters, showTimeoutMessage, showErrorMessage } = useValues(
        insightLogic
    )
    const { setActiveView } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { loadResults } = useActions(logicFromInsight(activeView, { dashboardItemId: null, filters: allFilters }))
    const dateFilterDisabled = activeView === ViewType.FUNNELS && isFunnelEmpty(allFilters)

    return (
        <div className="actions-graph">
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
                                type={activeView === 'history' && 'primary'}
                                data-attr="insight-history-button"
                                onClick={() => setActiveView('history')}
                            >
                                History
                            </Button>
                        ),
                    }}
                >
                    <TabPane tab={<span data-attr="insight-trends-tab">Trends</span>} key={ViewType.TRENDS} />
                    <TabPane tab={<span data-attr="insight-funnels-tab">Funnels</span>} key={ViewType.FUNNELS} />
                    <TabPane tab={<span data-attr="insight-sessions-tab">Sessions</span>} key={ViewType.SESSIONS} />
                    <TabPane tab={<span data-attr="insight-retention-tab">Retention</span>} key={ViewType.RETENTION} />
                    <TabPane tab={<span data-attr="insight-path-tab">User Paths</span>} key={ViewType.PATHS} />
                    {featureFlags['remove-shownas'] && (
                        <TabPane
                            tab={<span data-attr="insight-stickiness-tab">Stickiness</span>}
                            key={ViewType.STICKINESS}
                        />
                    )}
                    {featureFlags['remove-shownas'] && (
                        <TabPane
                            tab={<span data-attr="insight-lifecycle-tab">Lifecycle</span>}
                            key={ViewType.LIFECYCLE}
                        />
                    )}
                </Tabs>
            </Row>
            <Row gutter={16}>
                {activeView === 'history' ? (
                    <Col xs={24} xl={24}>
                        <Card className="" style={{ overflow: 'visible' }}>
                            <InsightHistoryPanel onChange={() => setOpenHistory(false)} />
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
                                              [`${ViewType.SESSIONS}`]: <SessionTab view={ViewType.SESSIONS} />,
                                              [`${ViewType.FUNNELS}`]: <FunnelTab />,
                                              [`${ViewType.RETENTION}`]: <RetentionTab />,
                                              [`${ViewType.PATHS}`]: <PathTab />,
                                          }[activeView]
                                        : {
                                              [`${ViewType.TRENDS}`]: <TrendTab view={ViewType.TRENDS} />,
                                              [`${ViewType.SESSIONS}`]: <SessionTab view={ViewType.SESSIONS} />,
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
                                    <div className="float-right">
                                        {showIntervalFilter(activeView, allFilters) && (
                                            <IntervalFilter filters={allFilters} view={activeView} />
                                        )}
                                        {showChartFilter(activeView, featureFlags) && (
                                            <ChartFilter
                                                onChange={(display) => {
                                                    if (display === ACTIONS_TABLE || display === ACTIONS_PIE_CHART) {
                                                        clearAnnotationsToCreate()
                                                    }
                                                }}
                                                filters={allFilters}
                                                disabled={allFilters.shown_as === LIFECYCLE}
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
                                }
                                headStyle={{ backgroundColor: 'rgba(0,0,0,.03)' }}
                            >
                                <div>
                                    {lastRefresh && (
                                        <small style={{ position: 'absolute', marginTop: -21, right: 24 }}>
                                            Computed {moment(lastRefresh).fromNow()}
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
                        </Col>
                    </>
                )}
            </Row>
        </div>
    )
}

const isFunnelEmpty = (filters) => {
    return (!filters.actions && !filters.events) || (filters.actions?.length === 0 && filters.events?.length === 0)
}

function FunnelInsight() {
    const { stepsWithCount, resultsLoading } = useValues(funnelLogic({}))

    return (
        <div style={{ height: 300, position: 'relative' }}>
            {resultsLoading && <Loading />}
            {stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1 ? (
                <FunnelViz steps={stepsWithCount} />
            ) : (
                !resultsLoading && (
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

function FunnelPeople() {
    const { stepsWithCount } = useValues(funnelLogic())
    if (stepsWithCount && stepsWithCount.length > 0) {
        return <People />
    }
    return <></>
}
