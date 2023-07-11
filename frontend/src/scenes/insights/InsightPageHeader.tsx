import { EditableField } from 'lib/components/EditableField/EditableField'

import {
    AvailableFeature,
    ExporterFormat,
    FilterType,
    InsightLogicProps,
    InsightModel,
    InsightShortId,
    ItemMode,
} from '~/types'
import { IconDataObject, IconLock } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { urls } from 'scenes/urls'
import { SubscribeButton, SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { deleteWithUndo } from 'lib/utils'
import { AddToDashboard } from 'lib/components/AddToDashboard/AddToDashboard'
import { InsightSaveButton } from 'scenes/insights/InsightSaveButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { PageHeader } from 'lib/components/PageHeader'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightCommandLogic } from 'scenes/insights/insightCommandLogic'
import { userLogic } from 'scenes/userLogic'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { tagsModel } from '~/models/tagsModel'
import { teamLogic } from 'scenes/teamLogic'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { Tooltip } from 'antd'
import { LemonSwitch, LemonTag } from '@posthog/lemon-ui'
import { ThunderboltFilled } from '@ant-design/icons'
import { globalInsightLogic } from './globalInsightLogic'
import { isInsightVizNode } from '~/queries/utils'
import { posthog } from 'posthog-js'
import { summarizeInsight } from 'scenes/insights/summarizeInsight'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function InsightPageHeader({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const showRefreshInMenu = !featureFlags[FEATURE_FLAGS.REFRESH_BUTTON_ON_INSIGHT]

    // insightSceneLogic
    const { insightMode, subscriptionId } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    // insightLogic
    const logic = insightLogic(insightLogicProps)
    const {
        insightProps,
        filters,
        canEditInsight,
        insight,
        insightChanged,
        insightSaving,
        hasDashboardItemId,
        exporterResourceParams,
    } = useValues(logic)
    const { setInsightMetadata, saveAs } = useActions(logic)

    // savedInsightsLogic
    const { duplicateInsight, loadInsights } = useActions(savedInsightsLogic)

    // insightDataLogic
    const { query, queryChanged, showQueryEditor, getInsightRefreshButtonDisabledReason } = useValues(
        insightDataLogic(insightProps)
    )
    const {
        saveInsight: saveQueryBasedInsight,
        toggleQueryEditorPanel,
        loadData,
    } = useActions(insightDataLogic(insightProps))

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { mathDefinitions } = useValues(mathsLogic)
    const { tags } = useValues(tagsModel)
    const { currentTeamId } = useValues(teamLogic)
    const { push } = useActions(router)
    const { globalInsightFilters } = useValues(globalInsightLogic)
    const { setGlobalInsightFilters } = useActions(globalInsightLogic)

    usePeriodicRerender(30000) // Re-render every 30 seconds for up-to-date `insightRefreshButtonDisabledReason`

    const insightRefreshButtonDisabledReason = getInsightRefreshButtonDisabledReason()

    return (
        <>
            {hasDashboardItemId && (
                <>
                    <SubscriptionsModal
                        isOpen={insightMode === ItemMode.Subscriptions}
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        insightShortId={insight.short_id}
                        subscriptionId={subscriptionId}
                    />
                    <SharingModal
                        title="Insight Sharing"
                        isOpen={insightMode === ItemMode.Sharing}
                        closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
                        insightShortId={insight.short_id}
                        insight={insight}
                        previewIframe
                    />
                </>
            )}
            <PageHeader
                title={
                    <EditableField
                        name="name"
                        value={insight.name || ''}
                        placeholder={summarizeInsight(query, filters, {
                            aggregationLabel,
                            cohortsById,
                            mathDefinitions,
                        })}
                        onSave={(value) => setInsightMetadata({ name: value })}
                        saveOnBlur={true}
                        maxLength={400} // Sync with Insight model
                        mode={!canEditInsight ? 'view' : undefined}
                        data-attr="insight-name"
                        notice={
                            !canEditInsight
                                ? {
                                      icon: <IconLock />,
                                      tooltip:
                                          "You don't have edit permissions on any of the dashboards this insight belongs to. Ask a dashboard collaborator with edit access to add you.",
                                  }
                                : undefined
                        }
                    />
                }
                buttons={
                    <div className="flex justify-between items-center gap-2">
                        {!hasDashboardItemId ? (
                            <>
                                {showRefreshInMenu ? (
                                    <>
                                        <More
                                            overlay={
                                                <>
                                                    <LemonButton
                                                        status="stealth"
                                                        onClick={() => loadData(true)}
                                                        fullWidth
                                                        data-attr="refresh-insight-from-insight-view"
                                                        disabledReason={insightRefreshButtonDisabledReason}
                                                    >
                                                        Refresh
                                                    </LemonButton>
                                                </>
                                            }
                                        />
                                        <LemonDivider vertical />
                                    </>
                                ) : (
                                    <></>
                                )}
                            </>
                        ) : (
                            <>
                                <More
                                    overlay={
                                        <>
                                            {showRefreshInMenu && (
                                                <LemonButton
                                                    status="stealth"
                                                    onClick={() => loadData(true)}
                                                    fullWidth
                                                    data-attr="refresh-insight-from-insight-view"
                                                    disabledReason={insightRefreshButtonDisabledReason}
                                                >
                                                    Refresh
                                                </LemonButton>
                                            )}
                                            <LemonButton
                                                status="stealth"
                                                onClick={() => duplicateInsight(insight as InsightModel, true)}
                                                fullWidth
                                                data-attr="duplicate-insight-from-insight-view"
                                            >
                                                Duplicate
                                            </LemonButton>
                                            <LemonButton
                                                status="stealth"
                                                onClick={() =>
                                                    setInsightMetadata({
                                                        favorited: !insight.favorited,
                                                    })
                                                }
                                                fullWidth
                                            >
                                                {insight.favorited ? 'Remove from favorites' : 'Add to favorites'}
                                            </LemonButton>
                                            <LemonDivider />

                                            <LemonButton
                                                status="stealth"
                                                onClick={() =>
                                                    insight.short_id
                                                        ? push(urls.insightSharing(insight.short_id))
                                                        : null
                                                }
                                                fullWidth
                                            >
                                                Share or embed
                                            </LemonButton>
                                            {insight.short_id && (
                                                <>
                                                    <SubscribeButton insightShortId={insight.short_id} />
                                                    {exporterResourceParams ? (
                                                        <ExportButton
                                                            fullWidth
                                                            items={[
                                                                {
                                                                    export_format: ExporterFormat.PNG,
                                                                    insight: insight.id,
                                                                },
                                                                {
                                                                    export_format: ExporterFormat.CSV,
                                                                    export_context: exporterResourceParams,
                                                                },
                                                            ]}
                                                        />
                                                    ) : null}
                                                    <LemonDivider />
                                                </>
                                            )}

                                            <LemonButton
                                                status="danger"
                                                onClick={() =>
                                                    deleteWithUndo({
                                                        object: insight,
                                                        endpoint: `projects/${currentTeamId}/insights`,
                                                        callback: () => {
                                                            loadInsights()
                                                            push(urls.savedInsights())
                                                        },
                                                    })
                                                }
                                                fullWidth
                                            >
                                                Delete insight
                                            </LemonButton>
                                        </>
                                    }
                                />
                                <LemonDivider vertical />
                            </>
                        )}

                        <>
                            <Tooltip
                                title="Turning on fast mode will automatically enable 10% sampling for all insights you refresh, speeding up the calculation of results"
                                placement="bottom"
                            >
                                <div>
                                    <LemonSwitch
                                        onChange={(checked) => {
                                            let samplingFilter: { sampling_factor: FilterType['sampling_factor'] } = {
                                                sampling_factor: null,
                                            }
                                            if (checked) {
                                                samplingFilter = { sampling_factor: 0.1 }
                                                posthog.capture('sampling_fast_mode_enabled')
                                            } else {
                                                posthog.capture('sampling_fast_mode_disabled')
                                            }
                                            setGlobalInsightFilters({ ...globalInsightFilters, ...samplingFilter })
                                        }}
                                        checked={!!globalInsightFilters.sampling_factor}
                                        icon={
                                            <ThunderboltFilled
                                                style={
                                                    !!globalInsightFilters.sampling_factor
                                                        ? { color: 'var(--primary)' }
                                                        : {}
                                                }
                                            />
                                        }
                                    />
                                </div>
                            </Tooltip>
                            <LemonDivider vertical />
                        </>

                        {insightMode === ItemMode.Edit && hasDashboardItemId && (
                            <LemonButton type="secondary" onClick={() => setInsightMode(ItemMode.View, null)}>
                                Cancel
                            </LemonButton>
                        )}
                        {insightMode !== ItemMode.Edit && hasDashboardItemId && (
                            <AddToDashboard insight={insight} canEditInsight={canEditInsight} />
                        )}

                        {insightMode !== ItemMode.Edit ? (
                            canEditInsight && (
                                <LemonButton
                                    type="primary"
                                    onClick={() => setInsightMode(ItemMode.Edit, null)}
                                    data-attr="insight-edit-button"
                                >
                                    Edit
                                </LemonButton>
                            )
                        ) : (
                            <InsightSaveButton
                                saveAs={saveAs}
                                saveInsight={saveQueryBasedInsight}
                                isSaved={hasDashboardItemId}
                                addingToDashboard={!!insight.dashboards?.length && !insight.id}
                                insightSaving={insightSaving}
                                insightChanged={insightChanged || queryChanged}
                            />
                        )}
                        {isInsightVizNode(query) ? (
                            <LemonButton
                                tooltip={
                                    showQueryEditor ? (
                                        <>
                                            Hide source
                                            <LemonTag className="ml-2" type="warning">
                                                BETA
                                            </LemonTag>
                                        </>
                                    ) : (
                                        <>
                                            View source
                                            <LemonTag className="ml-2" type="warning">
                                                BETA
                                            </LemonTag>
                                        </>
                                    )
                                }
                                aria-label={showQueryEditor ? 'Hide source (BETA)' : 'View source (BETA)'}
                                tooltipPlacement="bottomRight"
                                type={'secondary'}
                                onClick={() => {
                                    // for an existing insight in view mode
                                    if (hasDashboardItemId && insightMode !== ItemMode.Edit) {
                                        // enter edit mode
                                        setInsightMode(ItemMode.Edit, null)

                                        // exit early if query editor doesn't need to be toggled
                                        if (showQueryEditor !== false) {
                                            return
                                        }
                                    }
                                    toggleQueryEditorPanel()
                                }}
                                icon={<IconDataObject fontSize="18" />}
                            />
                        ) : null}
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
                                saveOnBlur={true}
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
                                saving={insightSaving}
                                onChange={(_, tags) => setInsightMetadata({ tags: tags ?? [] })}
                                tagsAvailable={tags}
                                className="insight-metadata-tags"
                                data-attr="insight-tags"
                            />
                        ) : insight.tags?.length ? (
                            <ObjectTags
                                tags={insight.tags}
                                saving={insightSaving}
                                className="insight-metadata-tags"
                                data-attr="insight-tags"
                                staticOnly
                            />
                        ) : null}
                        <UserActivityIndicator
                            at={insight.last_modified_at}
                            by={insight.last_modified_by}
                            className="mt-2"
                        />
                    </>
                }
                tabbedPage={insightMode === ItemMode.Edit} // Insight type tabs are only shown in edit mode
            />
        </>
    )
}
