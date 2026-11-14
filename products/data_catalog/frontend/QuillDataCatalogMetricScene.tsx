import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { QuillConfirmDialog } from 'products/data_quality/frontend/QuillConfirmDialog'

import { METRIC_DESCRIPTION_MAX_LENGTH } from './common'
import { MetricSceneMenuBar } from './components/MetricSceneMenuBar'
import { QuillEditApprovedMetricDialog } from './components/QuillEditApprovedMetricDialog'
import { QuillMetricDefinition } from './components/QuillMetricDefinition'
import { QuillMetricMoreActions } from './components/QuillMetricMoreActions'
import { QuillMetricProvenance } from './components/QuillMetricProvenance'
import { QuillMetricSceneSkeleton } from './components/QuillMetricSceneSkeleton'
import { QuillMetricStatusCallouts } from './components/QuillMetricStatusCallouts'
import { QuillMetricSummary } from './components/QuillMetricSummary'
import { QuillRenameMetricDialog } from './components/QuillRenameMetricDialog'
import {
    dataCatalogMetricSceneLogic,
    DataCatalogMetricSceneLogicProps,
    MetricSceneTab,
} from './dataCatalogMetricSceneLogic'
import type { PatchedDataCatalogMetricApi } from './generated/api.schemas'
import { buildMetricSceneActions, MAX_UNAVAILABLE_REASON, RUN_ACTION_KEY } from './metricSceneActions'
import { QuillMetricLineagePanel } from './QuillMetricLineagePanel'
import { QuillMetricTestsTab } from './tabs/QuillMetricTestsTab'
import { QuillMetricTestsTabLabel } from './tabs/QuillMetricTestsTabLabel'

type OpenDialog =
    | { kind: 'rename' }
    | { kind: 'delete' }
    | { kind: 'edit-approved'; patch: PatchedDataCatalogMetricApi }

export function QuillDataCatalogMetricScene({ name }: DataCatalogMetricSceneLogicProps): JSX.Element {
    const {
        metric,
        metricLoading,
        mutating,
        runResult,
        runResultLoading,
        editingDefinition,
        draftMarkdown,
        activeTab,
        mountedTabs,
        lineage,
        lineageLoading,
        lineageProblem,
    } = useValues(dataCatalogMetricSceneLogic)
    const {
        approveMetric,
        refreshMetricFromInsight,
        deleteMetric,
        renameMetric,
        updateMetric,
        loadRunResult,
        loadLineage,
        setEditingDefinition,
        setDraftMarkdown,
        startEditingMarkdown,
        setActiveTab,
        runMetricWithAI,
    } = useActions(dataCatalogMetricSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { isMaxAvailable } = useValues(maxGlobalLogic)
    const [openDialog, setOpenDialog] = useState<OpenDialog | null>(null)

    if (metricLoading && !metric) {
        return <QuillMetricSceneSkeleton />
    }
    if (!metric) {
        return <NotFound object="metric" />
    }

    const isApproved = metric.status === 'approved'
    const closeDialog = (): void => setOpenDialog(null)

    const confirmAndUpdate = (patch: PatchedDataCatalogMetricApi): void => {
        if (!isApproved) {
            updateMetric(patch)
            return
        }
        setOpenDialog({ kind: 'edit-approved', patch })
    }

    const actions = buildMetricSceneActions({
        metric,
        mutating,
        running: runResultLoading,
        isMaxAvailable,
        handlers: {
            approve: approveMetric,
            refreshFromInsight: refreshMetricFromInsight,
            run: loadRunResult,
            runWithAI: runMetricWithAI,
            rename: () => setOpenDialog({ kind: 'rename' }),
            delete: () => setOpenDialog({ kind: 'delete' }),
        },
    })
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]
    const overflowActions = actions.filter((action) => action.key !== RUN_ACTION_KEY)

    return (
        <BindLogic logic={dataCatalogMetricSceneLogic} props={{ name }}>
            <SceneContent>
                <MetricSceneMenuBar actions={actions} />

                <SceneTitleSection
                    name={metric.display_name || metric.name}
                    description={metric.description}
                    resourceType={{ type: 'data_warehouse' }}
                    canEdit
                    onNameChange={(value) => updateMetric({ display_name: value })}
                    onDescriptionChange={(value) => confirmAndUpdate({ description: value })}
                    descriptionMaxLength={METRIC_DESCRIPTION_MAX_LENGTH}
                    renameDebounceMs={0}
                    saveOnBlur
                    actions={
                        sceneMenuBarEnabled ? undefined : (
                            <div data-quill>
                                <QuillMetricMoreActions actions={overflowActions} />
                            </div>
                        )
                    }
                />

                <div className="flex flex-col gap-4" data-quill>
                    <QuillMetricSummary
                        metric={metric}
                        saving={mutating}
                        onSaveUnit={(unit) => confirmAndUpdate({ unit })}
                        onSaveOwner={(owner) => updateMetric({ owner })}
                    />
                    <QuillMetricStatusCallouts
                        metric={metric}
                        mutating={mutating}
                        onApprove={approveMetric}
                        onRefreshFromInsight={refreshMetricFromInsight}
                    />

                    <Tabs value={activeTab} onValueChange={(tab: MetricSceneTab) => setActiveTab(tab)}>
                        <TabsList variant="line" aria-label="Metric sections">
                            <TabsTrigger value="definition" data-attr="data-catalog-metric-tab-definition">
                                Definition
                            </TabsTrigger>
                            <TabsTrigger value="lineage" data-attr="data-catalog-metric-tab-lineage">
                                Lineage
                            </TabsTrigger>
                            <TabsTrigger value="data-quality" data-attr="data-catalog-metric-tab-data-quality">
                                <QuillMetricTestsTabLabel metricId={metric.id} />
                            </TabsTrigger>
                        </TabsList>

                        <TabsContent
                            value="definition"
                            keepMounted={mountedTabs.includes('definition')}
                            className="flex flex-col gap-4 pt-4"
                        >
                            {mountedTabs.includes('definition') && (
                                <>
                                    <QuillMetricDefinition
                                        metric={metric}
                                        editingDefinition={editingDefinition}
                                        draftMarkdown={draftMarkdown}
                                        saving={mutating}
                                        runResult={runResult}
                                        runResultLoading={runResultLoading}
                                        onDraftMarkdown={setDraftMarkdown}
                                        onEdit={setEditingDefinition}
                                        onStartEditingMarkdown={startEditingMarkdown}
                                        onSaveMarkdown={(markdown) =>
                                            confirmAndUpdate({ definition: { kind: 'MarkdownDefinition', markdown } })
                                        }
                                        onRun={loadRunResult}
                                        onRunWithAI={runMetricWithAI}
                                        runWithAIDisabledReason={isMaxAvailable ? undefined : MAX_UNAVAILABLE_REASON}
                                    />
                                    <QuillMetricProvenance metric={metric} />
                                </>
                            )}
                        </TabsContent>

                        <TabsContent value="lineage" keepMounted={mountedTabs.includes('lineage')} className="pt-4">
                            {mountedTabs.includes('lineage') && (
                                <QuillMetricLineagePanel
                                    metric={metric}
                                    lineage={lineage}
                                    lineageLoading={lineageLoading}
                                    lineageProblem={lineageProblem}
                                    onRetry={loadLineage}
                                    onEditDefinition={() => setActiveTab('definition')}
                                />
                            )}
                        </TabsContent>

                        <TabsContent
                            value="data-quality"
                            keepMounted={mountedTabs.includes('data-quality')}
                            className="flex flex-col gap-4 pt-4"
                        >
                            {mountedTabs.includes('data-quality') && <QuillMetricTestsTab />}
                        </TabsContent>
                    </Tabs>
                </div>

                {openDialog?.kind === 'edit-approved' && (
                    <QuillEditApprovedMetricDialog
                        open
                        isDrifted={!!metric.is_drifted}
                        onSaveAndApprove={() => {
                            updateMetric(openDialog.patch, true)
                            closeDialog()
                        }}
                        onSaveAndReset={() => {
                            updateMetric(openDialog.patch)
                            closeDialog()
                        }}
                        onCancel={closeDialog}
                    />
                )}
                {openDialog?.kind === 'rename' && (
                    <QuillRenameMetricDialog
                        currentName={metric.name}
                        isApproved={isApproved}
                        onRename={(newName) => {
                            renameMetric(newName)
                            closeDialog()
                        }}
                        onCancel={closeDialog}
                    />
                )}
                <QuillConfirmDialog
                    open={openDialog?.kind === 'delete'}
                    title="Delete metric?"
                    description={`This deletes ${metric.name} and makes its name available for a new metric. Queries and links that reference it will stop working.`}
                    confirmLabel="Delete"
                    onConfirm={() => {
                        deleteMetric()
                        closeDialog()
                    }}
                    onCancel={closeDialog}
                    dataAttr="data-catalog-metric-delete"
                />
            </SceneContent>
        </BindLogic>
    )
}
