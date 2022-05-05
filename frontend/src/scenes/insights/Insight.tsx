import './Insight.scss'
import React, { useEffect } from 'react'
import { useActions, useMountedLogic, useValues, BindLogic } from 'kea'
import { Card } from 'antd'
import { FunnelTab, PathTab, RetentionTab, TrendTab } from './InsightTabs'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightLogic } from './insightLogic'
import { insightCommandLogic } from './insightCommandLogic'
import { ItemMode, InsightType, AvailableFeature, InsightShortId } from '~/types'
import { NPSPrompt } from 'lib/experimental/NPSPrompt'
import { SaveCohortModal } from 'scenes/trends/SaveCohortModal'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { InsightsNav } from './InsightsNav'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { InsightSaveButton } from './InsightSaveButton'
import { userLogic } from 'scenes/userLogic'
import { FeedbackCallCTA } from 'lib/experimental/FeedbackCallCTA'
import { PageHeader } from 'lib/components/PageHeader'
import { LastModified } from 'lib/components/InsightCard/LastModified'
import { IconLock } from 'lib/components/icons'
import { summarizeInsightFilters } from './utils'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { LemonButton } from 'lib/components/LemonButton'
import { useUnloadConfirmation } from 'lib/hooks/useUnloadConfirmation'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { getEditorFilters } from 'scenes/insights/EditorFilters/getEditorFilters'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { Tooltip } from 'lib/components/Tooltip'
import { InfoCircleOutlined } from '@ant-design/icons'
import { EditorFilterItemTitle } from './EditorFilters/EditorFilterItemTitle'

export function Insight({ insightId }: { insightId: InsightShortId | 'new' }): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const { setInsightMode, syncInsightChanged } = useActions(insightSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { user } = useValues(userLogic)
    const availableFeatures = user?.organization?.available_features || []

    const logic = insightLogic({ dashboardItemId: insightId || 'new' })
    const {
        insightProps,
        insightLoading,
        filtersKnown,
        filters,
        canEditInsight,
        activeView,
        insight,
        insightChanged,
        tagLoading,
        insightSaving,
    } = useValues(logic)
    useMountedLogic(insightCommandLogic(insightProps))
    const { saveInsight, setInsightMetadata, saveAs, cancelChanges, reportInsightViewedForRecentInsights } =
        useActions(logic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { cohortModalVisible } = useValues(personsModalLogic)
    const { saveCohortWithUrl, setCohortModalVisible } = useActions(personsModalLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { mathDefinitions } = useValues(mathsLogic)

    useEffect(() => {
        reportInsightViewedForRecentInsights()
    }, [insightId])

    const usingEditorPanels = featureFlags[FEATURE_FLAGS.INSIGHT_EDITOR_PANELS]

    useUnloadConfirmation(insightMode === ItemMode.Edit && insightChanged)

    useEffect(() => {
        syncInsightChanged(insightChanged)
    }, [insightChanged])

    // Show the skeleton if loading an insight for which we only know the id
    // This helps with the UX flickering and showing placeholder "name" text.
    if (insightId !== 'new' && insightLoading && !filtersKnown) {
        return <InsightSkeleton />
    }

    /* These are insight specific filters. They each have insight specific logics */
    const insightTabFilters = {
        [`${InsightType.TRENDS}`]: <TrendTab view={InsightType.TRENDS} />,
        [`${InsightType.STICKINESS}`]: <TrendTab view={InsightType.STICKINESS} />,
        [`${InsightType.LIFECYCLE}`]: <TrendTab view={InsightType.LIFECYCLE} />,
        [`${InsightType.FUNNELS}`]: <FunnelTab />,
        [`${InsightType.RETENTION}`]: <RetentionTab />,
        [`${InsightType.PATHS}`]: <PathTab />,
    }[activeView]

    // NOTE: Temp var whilst migrating to Editor Panels
    const isEditorPanelsDone = ![
        InsightType.TRENDS,
        InsightType.LIFECYCLE,
        InsightType.STICKINESS,
        InsightType.RETENTION,
        InsightType.PATHS,
        InsightType.FUNNELS,
    ].includes(filters.insight as InsightType)

    const insightTab = usingEditorPanels ? (
        <>
            {insight &&
                filters &&
                Object.entries(getEditorFilters(filters, featureFlags, availableFeatures))
                    .filter(([, v]) => v.length > 0)
                    .map(([title, editorFilters]) => {
                        return (
                            <div key={title} className="insights-filter-group">
                                <div className="insights-filter-group-title">{title}</div>
                                <div className="insights-filter-group-content">
                                    {editorFilters.map(
                                        ({ label, tooltip, key, valueSelector, component: Component }) => (
                                            <div key={key}>
                                                {label ? (
                                                    <EditorFilterItemTitle label={label} tooltip={tooltip} />
                                                ) : null}
                                                {Component ? (
                                                    <Component
                                                        insight={insight}
                                                        insightProps={insightProps}
                                                        filters={insight.filters ?? cleanFilters({})}
                                                        value={
                                                            (valueSelector
                                                                ? valueSelector(insight)
                                                                : insight?.filters?.[key]) ?? null
                                                        }
                                                    />
                                                ) : null}
                                            </div>
                                        )
                                    )}
                                </div>
                            </div>
                        )
                    })}
            {isEditorPanelsDone ? (
                <div style={{ margin: '1em' }}>
                    <div style={{ padding: '1em', background: 'var(--bg-mid)' }}>Old unstructured filters</div>
                    <div style={{ padding: '1em', background: '#fff', border: '1px solid var(--bg-mid)' }}>
                        {insightTabFilters}
                    </div>
                </div>
            ) : null}
        </>
    ) : (
        insightTabFilters
    )

    const insightScene = (
        <div className="insights-page">
            <PageHeader
                title={
                    <EditableField
                        name="name"
                        value={insight.name || ''}
                        placeholder={summarizeInsightFilters(filters, aggregationLabel, cohortsById, mathDefinitions)}
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
                        {insightMode === ItemMode.Edit && insight.saved && (
                            <LemonButton type="secondary" onClick={() => cancelChanges(true)}>
                                Cancel
                            </LemonButton>
                        )}
                        {insightMode === ItemMode.View && insight.short_id && <SaveToDashboard insight={insight} />}
                        {insightMode === ItemMode.View ? (
                            canEditInsight && (
                                <LemonButton
                                    type="primary"
                                    style={{ marginLeft: 8 }}
                                    onClick={() => setInsightMode(ItemMode.Edit, null)}
                                    data-attr="insight-edit-button"
                                >
                                    Edit
                                </LemonButton>
                            )
                        ) : (
                            <InsightSaveButton
                                saveAs={saveAs}
                                saveInsight={saveInsight}
                                isSaved={insight.saved}
                                addingToDashboard={!!insight.dashboards?.length && !insight.id}
                                insightSaving={insightSaving}
                                insightChanged={insightChanged}
                            />
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
                            />
                        )}
                        {canEditInsight ? (
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
                        ) : null}
                        <LastModified at={insight.last_modified_at} by={insight.last_modified_by} />
                    </>
                }
            />

            {usingEditorPanels ? (
                <div className="insights-wrapper">
                    {insightMode !== ItemMode.View ? (
                        <div className="insight-editor-area">
                            {/* These are insight specific filters. They each have insight specific logics */}
                            {insightTab}
                        </div>
                    ) : null}
                    <div className="insights-container">
                        <InsightContainer />
                    </div>
                </div>
            ) : (
                <>
                    {insightMode !== ItemMode.View ? (
                        <>
                            <InsightsNav />
                            <Card className="insight-controls">
                                <div className="tabs-inner">{insightTab}</div>
                            </Card>
                        </>
                    ) : null}
                    <InsightContainer />
                </>
            )}

            {insightMode !== ItemMode.View ? (
                <>
                    <NPSPrompt />
                    <FeedbackCallCTA />
                </>
            ) : null}

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
