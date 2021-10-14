import './Insights.scss'
import React from 'react'
import { useActions, useMountedLogic, useValues, BindLogic } from 'kea'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { Row, Col, Card, Button, Popconfirm, Tooltip } from 'antd'
import { FEATURE_FLAGS } from 'lib/constants'
import { annotationsLogic } from '~/lib/components/Annotations'
import { router } from 'kea-router'
import { FunnelTab, PathTab, RetentionTab, SessionTab, TrendTab } from './InsightTabs'
import { insightLogic } from './insightLogic'
import { InsightHistoryPanel } from './InsightHistoryPanel'
import { DownOutlined, UpOutlined } from '@ant-design/icons'
import { insightCommandLogic } from './insightCommandLogic'
import { HotKeys, ItemMode, ViewType } from '~/types'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { NPSPrompt } from 'lib/experimental/NPSPrompt'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SaveCohortModal } from 'scenes/trends/SaveCohortModal'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { InsightsNav } from './InsightsNav'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { InsightMetadata } from 'scenes/insights/InsightMetadata'

dayjs.extend(relativeTime)

export function Insights(): JSX.Element {
    useMountedLogic(insightCommandLogic)
    const {
        hashParams: { fromItem },
    } = useValues(router)

    const logic = insightLogic({ dashboardItemId: fromItem, syncWithUrl: true })
    const { insightProps, activeView, filters, controlsCollapsed, insight, insightMode } = useValues(logic)
    const { setActiveView, toggleControlsCollapsed, setInsightMode, saveInsight } = useActions(logic)
    const { annotationsToCreate } = useValues(annotationsLogic({ pageKey: fromItem }))
    const { reportHotkeyNavigation } = useActions(eventUsageLogic)
    const { cohortModalVisible } = useValues(personsModalLogic)
    const { saveCohortWithFilters, setCohortModalVisible } = useActions(personsModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { reportInsightsTabReset } = useActions(eventUsageLogic)

    const { reportCohortCreatedFromPersonModal } = useActions(eventUsageLogic)
    const verticalLayout = activeView === ViewType.FUNNELS && !featureFlags[FEATURE_FLAGS.FUNNEL_HORIZONTAL_UI] // Whether to display the control tab on the side instead of on top

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

    const scene = (
        <div className="insights-page">
            {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && insightMode === ItemMode.View ? (
                <div className="insight-metadata">
                    <Row justify="space-between" align="middle" style={{ marginTop: 24 }}>
                        <InsightMetadata.Title insight={insight} insightMode={insightMode} />
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
                                        filters: insight.filters || filters,
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
                    <InsightMetadata.Description insight={insight} insightMode={insightMode} />
                    <InsightMetadata.Tags insight={insight} insightMode={insightMode} />
                    <Col span={24} style={{ marginTop: 16 }}>
                        <InsightContainer />
                    </Col>
                </div>
            ) : (
                <>
                    <SaveCohortModal
                        visible={cohortModalVisible}
                        onOk={(title: string) => {
                            saveCohortWithFilters(title, filters)
                            setCohortModalVisible(false)
                            reportCohortCreatedFromPersonModal(filters)
                        }}
                        onCancel={() => setCohortModalVisible(false)}
                    />

                    <div className="insight-metadata">
                        <Row align="middle" style={{ marginTop: 24, justifyContent: 'space-between' }}>
                            <Col style={{ flex: 1 }}>
                                <InsightMetadata.Title insight={insight} insightMode={insightMode} />
                            </Col>
                            <Col className="insights-tab-actions">
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
                                                filters: insight.filters || filters,
                                                annotations: annotationsToCreate,
                                            },
                                        }}
                                    />
                                    {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && (
                                        <Button style={{ marginLeft: 8 }} type="primary" onClick={() => saveInsight()}>
                                            Save
                                        </Button>
                                    )}
                                </>
                            </Col>
                        </Row>
                        <Row>
                            <InsightMetadata.Description insight={insight} insightMode={insightMode} />
                        </Row>
                        <Row>
                            <InsightMetadata.Tags insight={insight} insightMode={insightMode} />
                        </Row>
                    </div>

                    <Row style={{ marginTop: 16 }}>
                        <InsightsNav />
                    </Row>

                    <Row gutter={16}>
                        {(activeView as ViewType) === ViewType.HISTORY ? (
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
                                    <InsightContainer />
                                </Col>
                            </>
                        )}
                    </Row>
                    <NPSPrompt />
                </>
            )}
        </div>
    )

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            {scene}
        </BindLogic>
    )
}
