import './Insights.scss'
import React from 'react'
import { useActions, useMountedLogic, useValues, BindLogic } from 'kea'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { Row, Col, Card, Button, Popconfirm } from 'antd'
import { FEATURE_FLAGS } from 'lib/constants'
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
import { SceneExport } from 'scenes/sceneTypes'
import { HotkeyButton } from 'lib/components/HotkeyButton/HotkeyButton'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ObjectTags } from 'lib/components/ObjectTags'

dayjs.extend(relativeTime)

export const scene: SceneExport = {
    component: Insights,
    logic: insightLogic,
    paramsToProps: ({ hashParams: { fromItem } }) => ({ dashboardItemId: fromItem, syncWithUrl: true }),
}

export function Insights(): JSX.Element {
    useMountedLogic(insightCommandLogic)
    const {
        hashParams: { fromItem },
    } = useValues(router)

    const logic = insightLogic({ dashboardItemId: fromItem, syncWithUrl: true })
    const {
        insightProps,
        activeView,
        filters,
        controlsCollapsed,
        insight,
        insightMode,
        filtersChanged,
        savedFilters,
        tagLoading,
        metadataEditable,
    } = useValues(logic)
    const {
        setActiveView,
        toggleControlsCollapsed,
        setInsightMode,
        saveInsight,
        setFilters,
        setInsightMetadata,
        saveNewTag,
        deleteTag,
    } = useActions(logic)

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
        e: {
            action: () => setInsightMode(ItemMode.Edit, InsightEventSource.Hotkey),
            disabled: insightMode !== ItemMode.View,
        },
    })

    const viewMode = featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && insightMode === ItemMode.View

    const insightScene = (
        <div className="insights-page">
            <div className="insight-metadata">
                <Row justify="space-between" align="top" style={{ marginTop: 24 }}>
                    <Col xs={{ span: 24, order: 2 }} sm={{ order: 1 }} style={{ flex: 1 }}>
                        <EditableField
                            name="name"
                            value={insight.name || ''}
                            placeholder={`Insight #${insight.id ?? '...'}`}
                            onChange={(value) => setInsightMetadata({ name: value })}
                            className={'insight-metadata-name'}
                            dataAttr={'insight-name'}
                        />
                    </Col>
                    <Col
                        className="insights-tab-actions"
                        xs={{ span: 24, order: 1 }}
                        sm={{ order: 2 }}
                        style={{ flex: 0 }}
                    >
                        {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && filtersChanged ? (
                            <Popconfirm
                                title="Are you sure? This will discard all unsaved changes in this insight."
                                onConfirm={() => {
                                    setFilters(savedFilters)
                                    reportInsightsTabReset()
                                }}
                            >
                                <Button type="link" className="btn-reset">
                                    Discard changes
                                </Button>
                            </Popconfirm>
                        ) : null}
                        {insight.id && <SaveToDashboard insight={insight} />}
                        {viewMode ? (
                            <HotkeyButton
                                type="primary"
                                style={{ marginLeft: 8 }}
                                onClick={() => setInsightMode(ItemMode.Edit, null)}
                                hotkey="e"
                            >
                                Edit
                            </HotkeyButton>
                        ) : featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] ? (
                            <Button style={{ marginLeft: 8 }} type="primary" onClick={saveInsight}>
                                Save
                            </Button>
                        ) : null}
                    </Col>
                </Row>
                <EditableField
                    multiline
                    name="description"
                    value={insight.description || ''}
                    placeholder={`Description (optional)`}
                    onChange={(value) => setInsightMetadata({ description: value })}
                    className={'insight-metadata-description'}
                    dataAttr={'insight-description'}
                />
                {metadataEditable ? (
                    <div className={'insight-metadata-tags'} data-attr="insight-tags">
                        <ObjectTags
                            tags={insight.tags ?? []}
                            onTagSave={saveNewTag}
                            onTagDelete={deleteTag}
                            saving={tagLoading}
                            tagsAvailable={[]}
                        />
                    </div>
                ) : null}
            </div>

            {featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && insightMode === ItemMode.View ? (
                <Row>
                    <Col span={24} style={{ marginTop: 16 }}>
                        <InsightContainer />
                    </Col>
                </Row>
            ) : (
                <>
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

            <SaveCohortModal
                visible={cohortModalVisible}
                onOk={(title: string) => {
                    saveCohortWithFilters(title, filters)
                    setCohortModalVisible(false)
                    reportCohortCreatedFromPersonModal(filters)
                }}
                onCancel={() => setCohortModalVisible(false)}
            />
        </div>
    )

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            {insightScene}
        </BindLogic>
    )
}
