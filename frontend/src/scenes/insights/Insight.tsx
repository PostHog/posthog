import './Insight.scss'
import React from 'react'
import { useActions, useMountedLogic, useValues, BindLogic } from 'kea'
import { Row, Col, Card, Button, Popconfirm, Alert } from 'antd'
import { FEATURE_FLAGS } from 'lib/constants'
import { FunnelTab, PathTab, RetentionTab, SessionTab, TrendTab } from './InsightTabs'
import { insightLogic } from './insightLogic'
import { insightCommandLogic } from './insightCommandLogic'
import { HotKeys, ItemMode, InsightType, InsightShortId } from '~/types'
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
import { UNNAMED_INSIGHT_NAME } from './EmptyStates'
import { InsightSaveButton } from './InsightSaveButton'
import posthog from 'posthog-js'
import { helpButtonLogic } from 'lib/components/HelpButton/HelpButton'

export const scene: SceneExport = {
    component: Insight,
    logic: insightLogic,
    paramsToProps: ({ params: { shortId } }) => ({ dashboardItemId: shortId, syncWithUrl: true }),
}

export function Insight({ shortId }: { shortId?: InsightShortId } = {}): JSX.Element {
    useMountedLogic(insightCommandLogic)

    const logic = insightLogic({ dashboardItemId: shortId, syncWithUrl: true })
    const {
        insightProps,
        activeView,
        filters,
        insight,
        insightMode,
        filtersChanged,
        savedFilters,
        tagLoading,
        metadataEditable,
    } = useValues(logic)
    const {
        setActiveView,
        setInsightMode,
        saveInsight,
        setFilters,
        setInsightMetadata,
        saveNewTag,
        deleteTag,
        saveAs,
    } = useActions(logic)

    const { reportHotkeyNavigation } = useActions(eventUsageLogic)
    const { cohortModalVisible } = useValues(personsModalLogic)
    const { saveCohortWithFilters, setCohortModalVisible } = useActions(personsModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { reportInsightsTabReset } = useActions(eventUsageLogic)
    const { showHelp } = useActions(helpButtonLogic)

    const { reportCohortCreatedFromPersonsModal } = useActions(eventUsageLogic)
    const verticalLayout = activeView === InsightType.FUNNELS && !featureFlags[FEATURE_FLAGS.FUNNEL_HORIZONTAL_UI] // Whether to display the control tab on the side instead of on top

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
        o: {
            action: () => handleHotkeyNavigation(InsightType.SESSIONS, 'o'),
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

    /* These are insight specific filters. They each have insight specific logics */
    const insightTab = {
        [`${InsightType.TRENDS}`]: <TrendTab view={InsightType.TRENDS} />,
        [`${InsightType.STICKINESS}`]: <TrendTab view={InsightType.STICKINESS} />,
        [`${InsightType.LIFECYCLE}`]: <TrendTab view={InsightType.LIFECYCLE} />,
        [`${InsightType.SESSIONS}`]: <SessionTab />,
        [`${InsightType.FUNNELS}`]: <FunnelTab />,
        [`${InsightType.RETENTION}`]: <RetentionTab />,
        [`${InsightType.PATHS}`]: <PathTab />,
    }[activeView]

    const insightScene = (
        <div className="insights-page">
            <div className="insight-metadata">
                <Row justify="space-between" align="top" style={{ marginTop: 24 }}>
                    <Col xs={{ span: 24, order: 2 }} sm={{ order: 1 }} style={{ flex: 1 }}>
                        <EditableField
                            name="name"
                            value={insight.name || ''}
                            placeholder={UNNAMED_INSIGHT_NAME}
                            onChange={(value) => setInsightMetadata({ name: value })}
                            className="insight-metadata-name"
                            dataAttr="insight-name"
                        />
                    </Col>
                    <Col
                        className="insights-tab-actions"
                        xs={{ span: 24, order: 1 }}
                        sm={{ order: 2 }}
                        style={{ flex: 0 }}
                    >
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
                            <HotkeyButton
                                type="primary"
                                style={{ marginLeft: 8 }}
                                onClick={() => setInsightMode(ItemMode.Edit, null)}
                                data-attr="insight-edit-button"
                                hotkey="e"
                            >
                                Edit
                            </HotkeyButton>
                        ) : (
                            <InsightSaveButton saveAs={saveAs} saveInsight={saveInsight} isSaved={insight.saved} />
                        )}
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

                    {activeView === InsightType.SESSIONS && featureFlags[FEATURE_FLAGS.SESSION_INSIGHT_REMOVAL] && (
                        <Alert
                            style={{ marginBottom: 16 }}
                            type="warning"
                            showIcon
                            message={
                                <div>
                                    We're deprecating and removing this feature soon as session-based analytics is not
                                    fully supported in PostHog.{' '}
                                    <a
                                        href="https://posthog.com/blog/sessions-removal?utm_campaign=sessions-insight-deprecation&utm_medium=in-product"
                                        target="_blank"
                                        rel="noopener"
                                    >
                                        Read more
                                    </a>{' '}
                                    about this change in our docs.
                                    <div>
                                        <b>Still interested in this feature?</b>{' '}
                                        <Button
                                            type="link"
                                            onClick={() => {
                                                showHelp()
                                                posthog.capture('session removal still interested')
                                            }}
                                            style={{ paddingLeft: 0, paddingRight: 0 }}
                                        >
                                            Share your feedback
                                        </Button>
                                        .
                                    </div>
                                </div>
                            }
                        />
                    )}

                    <Row gutter={16} style={verticalLayout ? { marginBottom: 64 } : undefined}>
                        <Col span={24} xl={verticalLayout ? 8 : undefined}>
                            {featureFlags[FEATURE_FLAGS.FUNNEL_SIMPLE_MODE] && verticalLayout ? (
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
                </>
            )}

            <SaveCohortModal
                visible={cohortModalVisible}
                onOk={(title: string) => {
                    saveCohortWithFilters(title, filters)
                    setCohortModalVisible(false)
                    reportCohortCreatedFromPersonsModal(filters)
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
