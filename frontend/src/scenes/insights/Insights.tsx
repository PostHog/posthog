import React, { useState } from 'react'
import { useActions, useMountedLogic, useValues, BindLogic } from 'kea'

import { isMobile, Loading } from 'lib/utils'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

import { Tabs, Row, Col, Card, Button, Tooltip, Alert } from 'antd'
import { FUNNEL_VIZ, ACTIONS_TABLE, ACTIONS_BAR_CHART_VALUE, FEATURE_FLAGS } from 'lib/constants'
import { annotationsLogic } from '~/lib/components/Annotations'
import { router } from 'kea-router'

import { RetentionContainer } from 'scenes/retention/RetentionContainer'

import { Paths } from 'scenes/paths/Paths'

import { RetentionTab, SessionTab, TrendTab, PathTab, FunnelTab } from './InsightTabs'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic, logicFromInsight } from './insightLogic'
import { InsightHistoryPanel } from './InsightHistoryPanel'
import { DownOutlined, UpOutlined } from '@ant-design/icons'
import { insightCommandLogic } from './insightCommandLogic'

import './Insights.scss'
import { ErrorMessage, FunnelEmptyState, FunnelInvalidFiltersEmptyState, TimeOut } from './EmptyStates'
import { People } from 'scenes/funnels/People'
import { InsightsTable } from './InsightsTable'
import { TrendInsight } from 'scenes/trends/Trends'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { FunnelVizType, HotKeys, ViewType } from '~/types'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { InsightDisplayConfig } from './InsightTabs/InsightDisplayConfig'
import { PageHeader } from 'lib/components/PageHeader'
import { NPSPrompt } from 'lib/experimental/NPSPrompt'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PersonModal } from 'scenes/trends/PersonModal'
import { SaveCohortModal } from 'scenes/trends/SaveCohortModal'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { FunnelCanvasLabel } from 'scenes/funnels/FunnelCanvasLabel'
import { FunnelHistogramHeader } from 'scenes/funnels/FunnelHistogram'
import clsx from 'clsx'
import { Funnel } from 'scenes/funnels/Funnel'
import { FunnelStepTable } from './InsightTabs/FunnelTab/FunnelStepTable'
import { FunnelSecondaryTabs } from './InsightTabs/FunnelTab/FunnelSecondaryTabs'

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
    const { reportHotkeyNavigation } = useActions(eventUsageLogic)
    const { showingPeople } = useValues(personsModalLogic)
    const { areFiltersValid } = useValues(funnelLogic)
    const { saveCohortWithFilters, refreshCohort } = useActions(personsModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)

    const { cohortModalVisible } = useValues(personsModalLogic)
    const { setCohortModalVisible } = useActions(personsModalLogic)
    const { reportCohortCreatedFromPersonModal } = useActions(eventUsageLogic)

    const verticalLayout = activeView === ViewType.FUNNELS // Whether to display the control tab on the side instead of on top

    const { loadResults } = useActions(logicFromInsight(activeView, { dashboardItemId: null, filters: allFilters }))

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
        i: {
            action: () => handleHotkeyNavigation(ViewType.STICKINESS, 'i'),
        },
        l: {
            action: () => handleHotkeyNavigation(ViewType.LIFECYCLE, 'l'),
        },
    })

    return (
        <div className="insights-page">
            <PersonModal
                visible={showingPeople && !cohortModalVisible}
                view={ViewType.FUNNELS}
                filters={allFilters}
                onSaveCohort={() => {
                    refreshCohort()
                    setCohortModalVisible(true)
                }}
            />
            <SaveCohortModal
                visible={cohortModalVisible}
                onOk={(title: string) => {
                    saveCohortWithFilters(title, allFilters)
                    setCohortModalVisible(false)
                    reportCohortCreatedFromPersonModal(allFilters)
                }}
                onCancel={() => setCohortModalVisible(false)}
            />
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
                                        Stickiness shows you how many days users performed an action repeatedly within a
                                        timeframe.
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
                                <InsightHotkey hotkey="i" />
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
                    <Col span={24}>
                        <Card className="" style={{ overflow: 'visible' }}>
                            <InsightHistoryPanel />
                        </Card>
                    </Col>
                ) : (
                    <>
                        <Col span={24} lg={verticalLayout ? 7 : undefined}>
                            <Card
                                className={`insight-controls${controlsCollapsed ? ' collapsed' : ''}`}
                                onClick={() => controlsCollapsed && toggleControlsCollapsed()}
                            >
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
                                            Click here to view and change the query events, filters and other settings.
                                        </span>
                                    </div>
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
                                            [`${ViewType.FUNNELS}`]: <FunnelTab />,
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
                            <FunnelSecondaryTabs />
                        </Col>
                        <Col span={24} lg={verticalLayout ? 17 : undefined}>
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
                                    />
                                }
                                data-attr="insights-graph"
                                className="insights-graph-container"
                            >
                                <div>
                                    <Row
                                        style={{
                                            justifyContent: 'space-between',
                                            alignItems: 'center',
                                            marginTop: -8,
                                            marginBottom: 16,
                                        }}
                                    >
                                        <FunnelCanvasLabel />
                                        <FunnelHistogramHeader />
                                        {lastRefresh && dayjs().subtract(3, 'minutes') > dayjs(lastRefresh) && (
                                            <div className="text-muted-alt">
                                                Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}{' '}
                                                &bull;
                                                <Button
                                                    size="small"
                                                    type="link"
                                                    onClick={() => loadResults(true)}
                                                    style={{ margin: 0 }}
                                                >
                                                    <span style={{ fontSize: 14 }}>Refresh</span>
                                                </Button>
                                            </div>
                                        )}
                                    </Row>
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
                            {(!featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] ||
                                (featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] && !preflight?.is_clickhouse_enabled)) &&
                                !showErrorMessage &&
                                !showTimeoutMessage &&
                                areFiltersValid &&
                                activeView === ViewType.FUNNELS &&
                                allFilters.display === FUNNEL_VIZ && <People />}
                            {featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] &&
                                preflight?.is_clickhouse_enabled &&
                                activeView === ViewType.FUNNELS &&
                                allFilters.funnel_viz_type === FunnelVizType.Steps && <FunnelStepTable />}
                            {(!allFilters.display ||
                                (allFilters.display !== ACTIONS_TABLE &&
                                    allFilters.display !== ACTIONS_BAR_CHART_VALUE)) &&
                                (activeView === ViewType.TRENDS || activeView === ViewType.SESSIONS) && (
                                    /* InsightsTable is loaded for all trend views (except below), plus the sessions view.
                                    Exclusions:
                                        1. Table view. Because table is already loaded anyways in `Trends.tsx` as the main component.
                                        2. Bar value chart. Because this view displays data in completely different dimensions.
                                    */
                                    <Card style={{ marginTop: 8 }}>
                                        <BindLogic
                                            logic={trendsLogic}
                                            props={{ dashboardItemId: null, view: activeView, filters: allFilters }}
                                        >
                                            <h3 className="l3">Details table</h3>
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
    const {
        isValidFunnel,
        isLoading,
        filters: { funnel_viz_type },
        areFiltersValid,
        filtersDirty,
        clickhouseFeaturesEnabled,
    } = useValues(funnelLogic({}))
    const { loadResults } = useActions(funnelLogic({}))
    const { featureFlags } = useValues(featureFlagLogic)

    const renderFunnel = (): JSX.Element => {
        if (isValidFunnel) {
            return <Funnel filters={{ funnel_viz_type }} />
        }
        if (!areFiltersValid) {
            return <FunnelInvalidFiltersEmptyState />
        }
        return isLoading ? <div style={{ height: 50 }} /> : <FunnelEmptyState />
    }

    return (
        <div
            className={clsx('funnel-insights-container', {
                'non-empty-state':
                    isValidFunnel &&
                    areFiltersValid &&
                    (!featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] || funnel_viz_type === FunnelVizType.Trends),
                'dirty-state': filtersDirty && !clickhouseFeaturesEnabled,
            })}
        >
            {filtersDirty && areFiltersValid && !isLoading && !clickhouseFeaturesEnabled ? (
                <div className="dirty-label">
                    <Alert
                        message={
                            <>
                                The filters have changed.{' '}
                                <Button onClick={loadResults}>Click to recalculate the funnel.</Button>
                            </>
                        }
                        type="warning"
                        showIcon
                    />
                </div>
            ) : null}
            {isLoading && <Loading />}
            {renderFunnel()}
        </div>
    )
}
