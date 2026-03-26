import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useMemo } from 'react'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { areAlertsSupportedForInsight } from 'lib/components/Alerts/insightAlertsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { urls } from 'scenes/urls'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { getLastNewFolder } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { isDataVisualizationNode } from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType, InsightLogicProps, ItemMode } from '~/types'

import { InsightSidePanelContent } from './SidePanel/InsightSidePanelContent'
import { getInsightIconTypeFromQuery, getOverrideWarningPropsForButton } from './utils'

export function InsightPageHeader({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const { insightMode, filtersOverride, variablesOverride, dashboardId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    const { insightProps, canEditInsight, insight, insightChanged, insightSaving, hasDashboardItemId, insightLoading } =
        useValues(insightLogic(insightLogicProps))
    const { setInsightMetadata, setInsightMetadataLocal, saveAs, saveInsight } = useActions(
        insightLogic(insightLogicProps)
    )

    const { query, queryChanged, insightQuery, generatedInsightMetadataLoading } = useValues(
        insightDataLogic(insightProps)
    )
    const { cancelChanges, generateInsightMetadata } = useActions(insightDataLogic(insightProps))

    const { featureFlags } = useValues(featureFlagLogic)
    const canAccessAutoname = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_AUTONAME_INSIGHTS_WITH_AI]

    const { push } = useActions(router)

    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const lastBreadcrumb = breadcrumbs[breadcrumbs.length - 1]
    const defaultInsightName =
        typeof lastBreadcrumb?.name === 'string' ? lastBreadcrumb.name : insight.name || insight.derived_name

    const canCreateAlertForInsight = areAlertsSupportedForInsight(query)

    useMaxTool({
        identifier: 'upsert_alert',
        active: canCreateAlertForInsight && hasDashboardItemId && !!insight.id,
        context: useMemo(
            () => ({
                insight_id: insight.id,
                insight_short_id: insight.short_id,
                insight_name: insight.name || insight.derived_name,
            }),
            [insight.id, insight.short_id, insight.name, insight.derived_name]
        ),
    })

    return (
        <>
            <InsightSidePanelContent insightLogicProps={insightLogicProps} />

            <SceneTitleSection
                name={defaultInsightName || ''}
                description={insight?.description || ''}
                resourceType={{
                    type: getInsightIconTypeFromQuery(query),
                }}
                onNameChange={(name) => {
                    if (insightMode === ItemMode.Edit) {
                        setInsightMetadataLocal({ name })
                    } else {
                        setInsightMetadata({ name })
                    }
                }}
                onDescriptionChange={(description) => {
                    if (insightMode === ItemMode.Edit) {
                        setInsightMetadataLocal({ description })
                    } else {
                        setInsightMetadata({ description })
                    }
                }}
                onGenerateMetadata={canAccessAutoname && insightQuery ? generateInsightMetadata : undefined}
                isGeneratingMetadata={canAccessAutoname && generatedInsightMetadataLoading}
                canEdit={canEditInsight}
                isLoading={insightLoading && !insight?.id}
                forceEdit={insightMode === ItemMode.Edit}
                renameDebounceMs={0}
                saveOnBlur
                descriptionMaxLength={400}
                actions={
                    <>
                        {insightMode === ItemMode.Edit && hasDashboardItemId && (
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    cancelChanges()
                                    setInsightMode(ItemMode.View, null)
                                }}
                                data-attr="insight-cancel-edit-button"
                                size="small"
                            >
                                Cancel
                            </LemonButton>
                        )}

                        {insightMode !== ItemMode.Edit ? (
                            canEditInsight && (
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Insight}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={insight.user_access_level}
                                >
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        tooltipPlacement="bottom"
                                        onClick={() => {
                                            if (isDataVisualizationNode(query) && insight.short_id) {
                                                router.actions.push(
                                                    urls.sqlEditor({ insightShortId: insight.short_id })
                                                )
                                            } else if (insight.short_id) {
                                                const editUrl = dashboardId
                                                    ? combineUrl(urls.insightEdit(insight.short_id), {
                                                          dashboard: dashboardId,
                                                      }).url
                                                    : urls.insightEdit(insight.short_id)
                                                push(editUrl)
                                            } else {
                                                setInsightMode(ItemMode.Edit, null)
                                            }
                                        }}
                                        {...getOverrideWarningPropsForButton(filtersOverride, variablesOverride)}
                                        data-attr="insight-edit-button"
                                    >
                                        Edit
                                    </LemonButton>
                                </AccessControlAction>
                            )
                        ) : (
                            <InsightSaveButton
                                saveAs={() => saveAs(undefined, undefined, 'Unfiled/Insights')}
                                saveInsight={(redirectToViewMode) =>
                                    insight.short_id
                                        ? saveInsight(redirectToViewMode)
                                        : saveInsight(redirectToViewMode, getLastNewFolder() ?? 'Unfiled/Insights')
                                }
                                isSaved={hasDashboardItemId}
                                addingToDashboard={!!insight.dashboards?.length && !insight.id}
                                insightSaving={insightSaving}
                                insightChanged={insightChanged || queryChanged}
                            />
                        )}
                    </>
                }
            />
        </>
    )
}
