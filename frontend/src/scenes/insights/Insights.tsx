import React from 'react'
import { useActions, useMountedLogic, useValues } from 'kea'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { Row, Col, Card, Input, Button, Popconfirm, Tooltip } from 'antd'
import { FEATURE_FLAGS } from 'lib/constants'
import { annotationsLogic } from '~/lib/components/Annotations'
import { router } from 'kea-router'
import { FunnelTab, PathTab, RetentionTab, SessionTab, TrendTab } from './InsightTabs'
import { insightLogic } from './insightLogic'
import { getLogicFromInsight } from './utils'
import { InsightHistoryPanel } from './InsightHistoryPanel'
import { DownOutlined, UpOutlined } from '@ant-design/icons'
import { insightCommandLogic } from './insightCommandLogic'
import { AvailableFeature, HotKeys, ItemMode, ViewType, InsightType } from '~/types'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { NPSPrompt } from 'lib/experimental/NPSPrompt'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SaveCohortModal } from 'scenes/trends/SaveCohortModal'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { ObjectTags } from 'lib/components/ObjectTags'
import { InsightsNav } from './InsightsNav'
import { userLogic } from 'scenes/userLogic'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { InsightContainer } from 'scenes/insights/InsightContainer'

import './Insights.scss'

dayjs.extend(relativeTime)

export function Insights(): JSX.Element {
    useMountedLogic(insightCommandLogic)
    const {
        hashParams: { fromItem },
    } = useValues(router)

    const { annotationsToCreate } = useValues(annotationsLogic({ pageKey: fromItem }))
    const { activeView, allFilters, controlsCollapsed, insight, insightMode, tagLoading } = useValues(insightLogic)
    const {
        setActiveView,
        toggleControlsCollapsed,
        saveNewTag,
        deleteTag,
        updateInsight,
        setInsightMode,
        setInsight,
        saveInsight,
    } = useActions(insightLogic)
    const { reportHotkeyNavigation } = useActions(eventUsageLogic)
    const { cohortModalVisible } = useValues(personsModalLogic)
    const { saveCohortWithFilters, setCohortModalVisible } = useActions(personsModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)
    const { reportInsightsTabReset } = useActions(eventUsageLogic)

    const { reportCohortCreatedFromPersonModal } = useActions(eventUsageLogic)
    const verticalLayout = activeView === ViewType.FUNNELS && !featureFlags[FEATURE_FLAGS.FUNNEL_HORIZONTAL_UI] // Whether to display the control tab on the side instead of on top

    const logicFromInsight = getLogicFromInsight(activeView as InsightType, {
        fromDashboardItemId: fromItem || null,
        filters: allFilters,
    })
    const { loadResults } = useActions(logicFromInsight)
    const { resultsLoading } = useValues(logicFromInsight)

    const handleHotkeyNavigation = (view: ViewType, hotkey: HotKeys): void => {
        setActiveView(view)
        reportHotkeyNavigation('insights', hotkey)
    }

    const { push } = useActions(router)

    useKeyboardHotkeys({
        t: {
            action: () => handleHotkeyNavigation(ViewType.TRENDS, 't'),
        },
        f: {
            action: () => handleHotkeyNavigation(ViewType.FUNNELS, 'f'),
        },
        o: {
            action: () => handleHotkeyNavigation(ViewType.SESSIONS, 'o'),
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
        escape: {
            // Exit edit mode with Esc. Full screen mode is also exited with Esc, but this behavior is native to the browser.
            action: () => setInsightMode(ItemMode.View, InsightEventSource.Hotkey),
            disabled: insightMode !== ItemMode.Edit,
        },
    })

    return (
        <div className="insights-page">
            {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && insightMode === ItemMode.View ? (
                <>
                    <Row justify="space-between" align="middle" style={{ marginTop: 24 }}>
                        <span style={{ fontSize: 28, fontWeight: 600 }}>
                            {insight.name || `Insight #${insight.id ?? '...'}`}
                        </span>
                        <div>
                            <SaveToDashboard
                                displayComponent={
                                    <Button style={{ color: 'var(--primary)' }} className="btn-save">
                                        Add to dashboard
                                    </Button>
                                }
                                tooltipOptions={{
                                    placement: 'bottom',
                                    title: 'Save to dashboard',
                                }}
                                item={{
                                    entity: {
                                        filters: insight.filters || allFilters,
                                        annotations: annotationsToCreate,
                                    },
                                }}
                            />
                            <Button
                                type="primary"
                                style={{ marginLeft: 8 }}
                                onClick={() => setInsightMode(ItemMode.Edit, null)}
                            >
                                Edit
                            </Button>
                        </div>
                    </Row>
                    {insight.description && (
                        <span className="text-muted-alt" style={{ fontStyle: 'italic' }}>
                            {insight.description}
                        </span>
                    )}
                    <div className="mb" style={{ marginTop: 8 }} data-attr="insight-tags">
                        <ObjectTags tags={insight.tags || []} staticOnly />
                    </div>
                    <Col span={24}>
                        <InsightContainer loadResults={loadResults} resultsLoading={resultsLoading} />
                    </Col>
                </>
            ) : (
                <>
                    <SaveCohortModal
                        visible={cohortModalVisible}
                        onOk={(title: string) => {
                            saveCohortWithFilters(title, allFilters)
                            setCohortModalVisible(false)
                            reportCohortCreatedFromPersonModal(allFilters)
                        }}
                        onCancel={() => setCohortModalVisible(false)}
                    />
                    {insight.id && (
                        <>
                            <Row
                                align="middle"
                                style={{ marginTop: 24, justifyContent: 'space-between' }}
                                className="mb-05"
                            >
                                {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] ? (
                                    <Col>
                                        <span style={{ fontSize: 28, fontWeight: 600 }}>
                                            {insight.saved ? 'Edit' : 'Create'} Insight
                                        </span>
                                    </Col>
                                ) : (
                                    <span style={{ fontSize: 28, fontWeight: 600 }}>
                                        {insight.name || `Insight #${insight.id}`}
                                    </span>
                                )}

                                <Col>
                                    <>
                                        <Popconfirm
                                            title="Are you sure? This will clear all filters and any progress will be lost."
                                            onConfirm={() => {
                                                window.scrollTo({ top: 0 })
                                                push(`/insights?insight=${insight?.filters?.insight}`)
                                                reportInsightsTabReset()
                                            }}
                                        >
                                            <Tooltip placement="top" title="Reset all filters">
                                                <Button type="link" className="btn-reset">
                                                    {'Reset'}
                                                </Button>
                                            </Tooltip>
                                        </Popconfirm>
                                        <SaveToDashboard
                                            displayComponent={
                                                <Button style={{ color: 'var(--primary)' }} className="btn-save">
                                                    {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS]
                                                        ? 'Save & add to dashboard'
                                                        : 'Add to dashboard'}
                                                </Button>
                                            }
                                            tooltipOptions={{
                                                placement: 'bottom',
                                                title: 'Save to dashboard',
                                            }}
                                            item={{
                                                entity: {
                                                    filters: insight.filters || allFilters,
                                                    annotations: annotationsToCreate,
                                                },
                                            }}
                                        />
                                        {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && (
                                            <Button
                                                style={{ marginLeft: 8 }}
                                                type="primary"
                                                onClick={() => saveInsight()}
                                            >
                                                Save
                                            </Button>
                                        )}
                                    </>
                                </Col>
                            </Row>
                            {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && (
                                <Row>
                                    <Col className="mt-05 mb-05">
                                        <span>
                                            <strong>Name</strong>
                                        </span>
                                        <div style={{ minWidth: 720 }}>
                                            <Input
                                                placeholder={insight.name || `Insight #${insight.id}`}
                                                value={insight.name || ''}
                                                size="large"
                                                style={{ minWidth: 720, marginTop: 8 }}
                                                onChange={(e) => setInsight({ ...insight, name: e.target.value })}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter') {
                                                        updateInsight(insight)
                                                    }
                                                }}
                                                tabIndex={0}
                                            />
                                        </div>
                                    </Col>
                                </Row>
                            )}
                        </>
                    )}

                    {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && (
                        <>
                            {user?.organization?.available_features?.includes(
                                AvailableFeature.DASHBOARD_COLLABORATION
                            ) && (
                                <>
                                    <Row>
                                        <Col style={{ paddingTop: 8 }}>
                                            <span>
                                                <strong>Description</strong>
                                            </span>
                                            <div style={{ minWidth: 720, marginTop: 8 }}>
                                                <Input.TextArea
                                                    value={insight.description}
                                                    onChange={(e) =>
                                                        setInsight({ ...insight, description: e.target.value })
                                                    }
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                                                            updateInsight(insight)
                                                        }
                                                    }}
                                                    tabIndex={5}
                                                    allowClear
                                                />
                                            </div>
                                        </Col>
                                    </Row>
                                    <Row>
                                        <Col style={{ paddingTop: 8 }}>
                                            <span>
                                                <strong>Tags</strong>
                                            </span>
                                            <div className="mb" style={{ marginTop: 8 }} data-attr="insight-tags">
                                                <ObjectTags
                                                    tags={insight.tags || []}
                                                    onTagSave={saveNewTag}
                                                    onTagDelete={deleteTag}
                                                    saving={tagLoading}
                                                    tagsAvailable={[]}
                                                />
                                            </div>
                                        </Col>
                                    </Row>
                                </>
                            )}
                        </>
                    )}

                    <Row style={{ marginTop: 16 }}>
                        <InsightsNav />
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
                                <Col span={24} xl={verticalLayout ? 8 : undefined}>
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
                                                    Click here to view and change the query events, filters and other
                                                    settings.
                                                </span>
                                            </div>
                                        )}
                                        <div className="tabs-inner">
                                            {/* These are insight specific filters. They each have insight specific logics */}
                                            {
                                                {
                                                    [`${ViewType.TRENDS}`]: <TrendTab view={ViewType.TRENDS} />,
                                                    [`${ViewType.STICKINESS}`]: <TrendTab view={ViewType.STICKINESS} />,
                                                    [`${ViewType.LIFECYCLE}`]: <TrendTab view={ViewType.LIFECYCLE} />,
                                                    [`${ViewType.SESSIONS}`]: <SessionTab />,
                                                    [`${ViewType.FUNNELS}`]: <FunnelTab />,
                                                    [`${ViewType.RETENTION}`]: <RetentionTab />,
                                                    [`${ViewType.PATHS}`]: <PathTab />,
                                                }[activeView]
                                            }
                                        </div>
                                    </Card>
                                </Col>
                                <Col span={24} xl={verticalLayout ? 16 : undefined}>
                                    <InsightContainer loadResults={loadResults} resultsLoading={resultsLoading} />
                                </Col>
                            </>
                        )}
                    </Row>
                    <NPSPrompt />
                </>
            )}
        </div>
    )
}
