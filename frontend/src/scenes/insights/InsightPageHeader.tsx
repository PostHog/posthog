import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { InsightSubscribeProminentButton } from 'lib/components/Scenes/InsightSubscribeProminentButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightModalsLogic } from 'scenes/insights/insightModalsLogic'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { urls } from 'scenes/urls'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { getLastNewFolder } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    isActorsQuery,
    isDataVisualizationNode,
    isEventsQuery,
    isGroupsQuery,
    isInsightQueryNode,
} from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType, InsightLogicProps, ItemMode } from '~/types'

import { areAlertsSupportedForInsight } from 'products/alerts/frontend/logic/insightAlertsLogic'

import { InsightSceneMenuBar } from './SidePanel/InsightSceneMenuBar'
import { InsightSidePanelContent } from './SidePanel/InsightSidePanelContent'
import { getInsightIconTypeFromQuery, getOverrideWarningPropsForButton } from './utils'

/** How long to wait for edit mode before re-issuing the navigation, and before giving up on it. */
const EDIT_MODE_RETRY_MS = 1500
const EDIT_MODE_GIVE_UP_MS = 5000

function supportsMetadataGeneration(node: Record<string, any> | null): boolean {
    return isInsightQueryNode(node) || isActorsQuery(node) || isEventsQuery(node) || isGroupsQuery(node)
}

export function InsightPageHeader({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const { insightMode, filtersOverride, variablesOverride, dashboardId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    const {
        insightProps,
        canEditInsight,
        insight,
        insightChanged,
        insightSaving,
        // `dashboardItemId` is legacy naming for the insight's own short_id — this is true when the insight is saved, not when it's on a dashboard
        hasDashboardItemId: isSavedInsight,
        insightLoading,
    } = useValues(insightLogic(insightLogicProps))
    const { setInsightMetadata, setInsightMetadataLocal, saveAs, saveInsight } = useActions(
        insightLogic(insightLogicProps)
    )
    const { openAddToDashboardModal, saveAndAddToDashboard } = useActions(insightModalsLogic(insightLogicProps))

    // A saved insight with its own short_id — the precondition for every view-mode action in this header.
    const isPersistedInsight = !!isSavedInsight && !!insight.short_id

    // New insights need a target folder; existing ones save in place. Shared by every save trigger in this header.
    const saveInsightToFolder = (redirectToViewMode?: boolean): void => {
        if (insight.short_id) {
            saveInsight(redirectToViewMode)
        } else {
            saveInsight(redirectToViewMode, getLastNewFolder() ?? 'Unfiled/Insights')
        }
    }

    const { query, queryChanged, insightQuery, generatedInsightMetadataLoading } = useValues(
        insightDataLogic(insightProps)
    )
    const { cancelChanges, generateInsightMetadata } = useActions(insightDataLogic(insightProps))
    const { push } = useActions(router)

    const goToEditMode = (): void => {
        if (isDataVisualizationNode(query) && insight.short_id) {
            push(
                urls.sqlEditor({
                    insightShortId: insight.short_id,
                    dashboard: dashboardId ?? undefined,
                    // Carry unsaved view-mode filter edits into the editor so they can be saved
                    filters: queryChanged ? query.source.filters : undefined,
                })
            )
        } else if (insight.short_id) {
            const editUrl = dashboardId
                ? combineUrl(urls.insightEdit(insight.short_id), { dashboard: dashboardId }).url
                : urls.insightEdit(insight.short_id)
            push(editUrl)
        } else {
            setInsightMode(ItemMode.Edit, null)
        }
    }
    const goToEditModeRef = useRef(goToEditMode)
    goToEditModeRef.current = goToEditMode

    // The editor only paints once the insight reloads, so the page can look untouched for seconds
    // after the click. Mark the button busy meanwhile, re-issue a navigation that never took, and
    // say so if edit mode still does not arrive, instead of leaving the click silently dropped.
    const [openingEditMode, setOpeningEditMode] = useState(false)
    useEffect(() => {
        if (!openingEditMode) {
            return
        }
        if (insightMode === ItemMode.Edit) {
            setOpeningEditMode(false)
            return
        }
        const retry = window.setTimeout(() => goToEditModeRef.current(), EDIT_MODE_RETRY_MS)
        const giveUp = window.setTimeout(() => {
            setOpeningEditMode(false)
            lemonToast.warning('Opening edit mode is taking longer than usual. Try again.')
        }, EDIT_MODE_GIVE_UP_MS)
        return () => {
            window.clearTimeout(retry)
            window.clearTimeout(giveUp)
        }
    }, [openingEditMode, insightMode])

    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const lastBreadcrumb = breadcrumbs[breadcrumbs.length - 1]
    const defaultInsightName =
        typeof lastBreadcrumb?.name === 'string' ? lastBreadcrumb.name : insight.name || insight.derived_name

    const metricsAlertsEnabled = useFeatureFlag('METRICS')
    const canCreateAlertForInsight = areAlertsSupportedForInsight(query, { metricsAlertsEnabled })

    const insightDisplayName = insight?.name || insight?.derived_name

    const readDataMaxToolProps = useMemo(
        () =>
            isSavedInsight && insight?.short_id
                ? {
                      identifier: 'read_data' as const,
                      context: {
                          insight_id: insight.id,
                          insight_short_id: insight.short_id,
                      },
                      contextDescription: {
                          text: insightDisplayName || 'Insight',
                          icon: iconForType(getInsightIconTypeFromQuery(query)),
                      },
                  }
                : undefined,
        [isSavedInsight, insight?.short_id, insight?.id, insightDisplayName, query]
    )

    useMaxTool({
        identifier: 'upsert_alert',
        active: canCreateAlertForInsight && isSavedInsight && !!insight.id,
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
            <InsightSceneMenuBar insightLogicProps={insightLogicProps} />

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
                onGenerateMetadata={supportsMetadataGeneration(insightQuery) ? generateInsightMetadata : undefined}
                isGeneratingMetadata={generatedInsightMetadataLoading}
                canEdit={canEditInsight}
                isLoading={insightLoading && !insight?.id}
                forceEdit={insightMode === ItemMode.Edit}
                renameDebounceMs={0}
                saveOnBlur={insightMode !== ItemMode.Edit}
                descriptionMaxLength={400}
                maxToolProps={readDataMaxToolProps}
                actions={
                    <>
                        {insightMode === ItemMode.Edit && isSavedInsight && (
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

                        {insightMode !== ItemMode.Edit && isPersistedInsight && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlusSmall />}
                                data-attr="insight-add-to-dashboard-prominent-button"
                                onClick={() => openAddToDashboardModal()}
                            >
                                Add to dashboard
                            </LemonButton>
                        )}

                        {insightMode !== ItemMode.Edit && isPersistedInsight && (
                            <InsightSubscribeProminentButton
                                insightShortId={insight.short_id!}
                                canCreateAlert={canCreateAlertForInsight}
                            />
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
                                        loading={openingEditMode}
                                        onClick={() => {
                                            setOpeningEditMode(true)
                                            goToEditMode()
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
                                saveInsight={saveInsightToFolder}
                                isSaved={isSavedInsight}
                                addingToDashboard={!!insight.dashboards?.length && !insight.id}
                                insightSaving={insightSaving}
                                insightChanged={insightChanged || queryChanged}
                                // Only offered for already-saved insights: the add-to-dashboard modal is keyed by the
                                // insight id, so saving a brand-new insight navigates to its real id and re-keys the
                                // modal logic, dropping the open state. New insights use the view-mode button instead.
                                // `saveAndAddToDashboard` owns the save-then-open ordering (see insightModalsLogic).
                                onSaveAndAddToDashboard={isPersistedInsight ? () => saveAndAddToDashboard() : undefined}
                            />
                        )}
                    </>
                }
            />
        </>
    )
}
