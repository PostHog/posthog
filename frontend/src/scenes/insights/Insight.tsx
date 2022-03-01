import './Insight.scss'
import React from 'react'
import { useActions, useMountedLogic, useValues, BindLogic } from 'kea'
import { Row, Col, Button, Popconfirm, Card } from 'antd'
import { FunnelTab, PathTab, RetentionTab, TrendTab } from './InsightTabs'
import { insightLogic } from './insightLogic'
import { insightCommandLogic } from './insightCommandLogic'
import { HotKeys, ItemMode, InsightType, InsightShortId, AvailableFeature } from '~/types'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { NPSPrompt } from 'lib/experimental/NPSPrompt'
import { SaveCohortModal } from 'scenes/trends/SaveCohortModal'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { InsightsNav } from './InsightsNav'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { SceneExport } from 'scenes/sceneTypes'
import { HotkeyButton } from 'lib/components/HotkeyButton/HotkeyButton'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { InsightSaveButton } from './InsightSaveButton'
import { userLogic } from 'scenes/userLogic'
import { FeedbackCallCTA } from 'lib/experimental/FeedbackCallCTA'
import { PageHeader } from 'lib/components/PageHeader'
import { LastModified } from 'lib/components/InsightCard/LastModified'
import { IconLock } from 'lib/components/icons'
import { determineSmartInsightName } from './utils'
import { groupsModel } from '~/models/groupsModel'

export const scene: SceneExport = {
    component: Insight,
    logic: insightLogic,
    paramsToProps: ({ params: { shortId } }) => ({ dashboardItemId: shortId, syncWithUrl: true }),
}

export function Insight({ shortId }: { shortId?: InsightShortId } = {}): JSX.Element {
    const logic = insightLogic({ dashboardItemId: shortId, syncWithUrl: true })
    const {
        insightProps,
        filters,
        canEditInsight,
        activeView,
        insight,
        insightMode,
        filtersChanged,
        savedFilters,
        tagLoading,
    } = useValues(logic)
    useMountedLogic(insightCommandLogic(insightProps))
    const { setActiveView, setInsightMode, saveInsight, setFilters, setInsightMetadata, saveAs } = useActions(logic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { reportHotkeyNavigation } = useActions(eventUsageLogic)
    const { cohortModalVisible } = useValues(personsModalLogic)
    const { saveCohortWithUrl, setCohortModalVisible } = useActions(personsModalLogic)
    const { reportInsightsTabReset } = useActions(eventUsageLogic)
    const { aggregationLabel } = useValues(groupsModel)

    // Whether to display the control tab on the side instead of on top
    const verticalLayout = activeView === InsightType.FUNNELS

    const handleHotkeyNavigation = (view: InsightType, hotkey: HotKeys): void => {
        setActiveView(view)
        reportHotkeyNavigation('insights', hotkey)
    }

    useKeyboardHotkeys({
        t: {
            action: () => handleHotkeyNavigation(InsightType.TRENDS, 't'),
        },
        f: {
            action: () => handleHotkeyNavigation(InsightType.FUNNELS, 'f'),
        },
        r: {
            action: () => handleHotkeyNavigation(InsightType.RETENTION, 'r'),
        },
        p: {
            action: () => handleHotkeyNavigation(InsightType.PATHS, 'p'),
        },
        i: {
            action: () => handleHotkeyNavigation(InsightType.STICKINESS, 'i'),
        },
        l: {
            action: () => handleHotkeyNavigation(InsightType.LIFECYCLE, 'l'),
        },
        e: {
            action: () => setInsightMode(ItemMode.Edit, InsightEventSource.Hotkey),
            disabled: insightMode !== ItemMode.View,
        },
    })

    /* These are insight specific filters. They each have insight specific logics */
    const insightTab = {
        [`${InsightType.TRENDS}`]: <TrendTab view={InsightType.TRENDS} />,
        [`${InsightType.STICKINESS}`]: <TrendTab view={InsightType.STICKINESS} />,
        [`${InsightType.LIFECYCLE}`]: <TrendTab view={InsightType.LIFECYCLE} />,
        [`${InsightType.FUNNELS}`]: <FunnelTab />,
        [`${InsightType.RETENTION}`]: <RetentionTab />,
        [`${InsightType.PATHS}`]: <PathTab />,
    }[activeView]

    const insightScene = (
        <div className="insights-page">
            <PageHeader
                title={
                    <EditableField
                        name="name"
                        value={insight.name || ''}
                        placeholder={determineSmartInsightName(filters, aggregationLabel)}
                        onSave={(value) => setInsightMetadata({ name: value })}
                        maxLength={400} // Sync with Insight model
                        mode={!canEditInsight ? 'view' : undefined}
                        data-attr="insight-name"
                        notice={
                            !canEditInsight
                                ? {
                                      icon: <IconLock />,
                                      tooltip:
                                          "You don't have edit permissions in the dashboard this insight belongs to. Ask a dashboard collaborator with edit access to add you.",
                                  }
                                : undefined
                        }
                    />
                }
                buttons={
                    <div className="insights-tab-actions">
                        {filtersChanged ? (
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
                        {insight.short_id && <SaveToDashboard insight={insight} />}
                        {insightMode === ItemMode.View ? (
                            canEditInsight && (
                                <HotkeyButton
                                    type="primary"
                                    style={{ marginLeft: 8 }}
                                    onClick={() => setInsightMode(ItemMode.Edit, null)}
                                    data-attr="insight-edit-button"
                                    hotkey="e"
                                >
                                    Edit
                                </HotkeyButton>
                            )
                        ) : (
                            <InsightSaveButton saveAs={saveAs} saveInsight={saveInsight} isSaved={insight.saved} />
                        )}
                    </div>
                }
                caption={
                    <>
                        {!!(canEditInsight || insight.description) && (
                            <EditableField
                                multiline
                                name="description"
                                value={insight.description || ''}
                                placeholder="Description (optional)"
                                onSave={(value) => setInsightMetadata({ description: value })}
                                maxLength={400} // Sync with Insight model
                                mode={!canEditInsight ? 'view' : undefined}
                                data-attr="insight-description"
                                compactButtons
                                paywall={!hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION)}
                                notice={
                                    !canEditInsight
                                        ? {
                                              icon: <IconLock />,
                                              tooltip:
                                                  "You don't have edit permissions in the dashboard this insight belongs to. Ask a dashboard collaborator with edit access to add you.",
                                          }
                                        : undefined
                                }
                            />
                        )}
                        {hasAvailableFeature(AvailableFeature.TAGGING) &&
                            (canEditInsight ? (
                                <ObjectTags
                                    tags={insight.tags ?? []}
                                    onChange={(_, tags) => setInsightMetadata({ tags: tags ?? [] })}
                                    saving={tagLoading}
                                    tagsAvailable={[]}
                                    className="insight-metadata-tags"
                                    data-attr="insight-tags"
                                />
                            ) : insight.tags?.length ? (
                                <ObjectTags
                                    tags={insight.tags}
                                    saving={tagLoading}
                                    className="insight-metadata-tags"
                                    data-attr="insight-tags"
                                    staticOnly
                                />
                            ) : null)}
                        <LastModified at={insight.last_modified_at} by={insight.last_modified_by} />
                    </>
                }
            />
            {insightMode === ItemMode.View ? (
                <Row style={{ marginTop: 16 }}>
                    <Col span={24}>
                        <InsightContainer />
                    </Col>
                </Row>
            ) : (
                <>
                    <Row style={{ marginTop: 8 }}>
                        <InsightsNav />
                    </Row>

                    <Row gutter={16} style={verticalLayout ? { marginBottom: 64 } : undefined}>
                        <Col span={24} xl={verticalLayout ? 8 : undefined}>
                            {verticalLayout ? (
                                insightTab
                            ) : (
                                <Card className="insight-controls">
                                    <div className="tabs-inner">
                                        {/* These are insight specific filters. They each have insight specific logics */}
                                        {insightTab}
                                    </div>
                                </Card>
                            )}
                        </Col>
                        <Col span={24} xl={verticalLayout ? 16 : undefined}>
                            <InsightContainer />
                        </Col>
                    </Row>
                    <NPSPrompt />
                    <FeedbackCallCTA />
                </>
            )}

            <SaveCohortModal
                visible={cohortModalVisible}
                onOk={(title: string) => {
                    saveCohortWithUrl(title)
                    setCohortModalVisible(false)
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
