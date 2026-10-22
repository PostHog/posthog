import { BindLogic, useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconEllipsis, IconPlus, IconShare } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonMenu, LemonModal, Spinner } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { isDataVisualizationNode } from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { buildBIAgentContext } from './biAgentContext'
import { BIChartAxis } from './BIChartAxisControls'
import { BIChartAxisModal } from './BIChartAxisModal'
import { BIEditor } from './BIEditor'
import { biEditorLogic } from './biEditorLogic'
import { BIEditorView } from './biEditorTypes'
import { getBIHierarchyParent } from './biHierarchies'
import { BIMetricProposalButton } from './BIMetricProposalButton'
import { BIResultSummary } from './BIResultSummary'
import { keepBIScatterRows } from './biScatter'
import { biSceneLogic } from './biSceneLogic'
import { BISQLPreviewModal } from './BISQLPreviewModal'

export const scene: SceneExport = {
    component: BusinessIntelligenceScene,
    logic: biSceneLogic,
    paramsToProps: ({ params }) => ({
        tabId: `bi-${params.tabId ?? 'default'}`,
    }),
}

export function BusinessIntelligenceScene({ tabId = 'bi-default' }: { tabId?: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activePanel, dataPaneFields, dataPaneFieldsLoading } = useValues(biEditorLogic({ tabId }))
    const { setActivePanel, startSuggestedChart, restoreState, runAfterChange } = useActions(biEditorLogic({ tabId }))
    const [settingsContainer, setSettingsContainer] = useState<HTMLDivElement | null>(null)
    const [editingAxis, setEditingAxis] = useState<BIChartAxis | null>(null)
    const logic = biSceneLogic({ tabId })
    const {
        name,
        lastRunQuery,
        insightLoading,
        catalogMetricLoading,
        loadError,
        hasUnsavedChanges,
        saveDisabledReason,
        exportViewOpen,
        exportViewName,
        exportedViewLoading,
        canUndo,
        canRedo,
        copyDisabledReason,
        worksheet,
        insight,
        displayedQueryIsCurrent,
        generatedQuery,
        currentTeamId,
        agentUpdateState,
    } = useValues(logic)
    const {
        setName,
        saveInsight,
        discardChanges,
        shareWorksheet,
        setVisualization,
        setChartSettings,
        setExportViewOpen,
        setExportViewName,
        exportView,
        undo,
        redo,
        navigateHierarchy,
        setSqlPreviewOpen,
        refreshInsightFromAgent,
        runQuery,
    } = useActions(logic)

    const hierarchyParent = getBIHierarchyParent(worksheet)

    const contextItems = useMemo(
        () => buildBIAgentContext(worksheet, insight?.short_id, name),
        [worksheet, insight?.short_id, name]
    )
    useSceneAgentPanel({
        sceneKey: 'business-intelligence',
        contextItems,
        active: !!featureFlags[FEATURE_FLAGS.SQL_EDITOR_BI_MODE],
        autoOpen: false,
        headlines: ['Build a worksheet from a catalog metric', 'What would you like to explore?'],
    })
    useMcpToolApplyBack({
        tools: ['insight-update'],
        targetKey: `bi-worksheet:${currentTeamId}:${insight?.id ?? 'unsaved'}`,
        active: !!insight && !!featureFlags[FEATURE_FLAGS.SQL_EDITOR_BI_MODE],
        onApply: (_event, { innerInput }) => refreshInsightFromAgent(innerInput),
    })

    useKeyboardHotkeys({
        z: {
            willHandleEvent: true,
            action: (event) => {
                if ((event.metaKey || event.ctrlKey) && !event.altKey && (event.shiftKey ? canRedo : canUndo)) {
                    event.preventDefault()
                    event.shiftKey ? redo() : undo()
                }
            },
        },
    })

    if (!featureFlags[FEATURE_FLAGS.SQL_EDITOR_BI_MODE]) {
        return <NotFound object="page" />
    }

    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied reason="You don't have access to Data warehouse tables & views, so Business intelligence isn't available." />
        )
    }

    return (
        <BindLogic logic={biSceneLogic} props={{ tabId }}>
            <div className="flex h-full min-h-0 flex-col" data-attr="bi-worksheet">
                <BISQLPreviewModal />
                <header className="flex flex-wrap items-center gap-1 border-b px-2 py-1">
                    <LemonButton size="small" to={urls.businessIntelligence()} tooltip="Back to Business Intelligence">
                        BI
                    </LemonButton>
                    <LemonButton size="small" icon={<IconPlus />} to={`${urls.businessIntelligenceNew()}#q=`}>
                        New worksheet
                    </LemonButton>
                    <LemonInput
                        aria-label="Worksheet name"
                        value={name}
                        onChange={setName}
                        maxLength={400}
                        size="small"
                        className="min-w-40 flex-1"
                    />
                    <LemonButton size="small" onClick={undo} disabledReason={!canUndo ? 'Nothing to undo' : undefined}>
                        Undo
                    </LemonButton>
                    <LemonButton size="small" onClick={redo} disabledReason={!canRedo ? 'Nothing to redo' : undefined}>
                        Redo
                    </LemonButton>
                    <LemonButton
                        size="small"
                        icon={<IconShare />}
                        onClick={shareWorksheet}
                        data-attr="bi-share-worksheet"
                    >
                        Share
                    </LemonButton>
                    <LemonMenu
                        items={[
                            {
                                label: 'View SQL',
                                onClick: () => setSqlPreviewOpen(true),
                                disabledReason:
                                    !generatedQuery && !lastRunQuery
                                        ? 'Select fields to build a query first'
                                        : undefined,
                                'data-attr': 'bi-view-sql',
                            },
                            {
                                label: 'Save a copy',
                                onClick: () => saveInsight({ asCopy: true }),
                                disabledReason: insightLoading ? 'Saving worksheet' : copyDisabledReason,
                                'data-attr': 'bi-save-copy',
                            },
                            {
                                label: 'Save as SQL view',
                                onClick: () => setExportViewOpen(true),
                                disabledReason:
                                    saveDisabledReason ||
                                    (!userHasAccess(
                                        AccessControlResourceType.WarehouseObjects,
                                        AccessControlLevel.Editor
                                    )
                                        ? 'You do not have permission to create warehouse views'
                                        : undefined),
                                'data-attr': 'bi-export-sql-view',
                            },
                            {
                                label: 'Discard changes',
                                onClick: () => discardChanges(),
                                disabledReason: !hasUnsavedChanges ? 'No changes to discard' : undefined,
                                'data-attr': 'bi-discard-changes',
                            },
                        ]}
                    >
                        <LemonButton
                            icon={<IconEllipsis />}
                            size="small"
                            aria-label="Worksheet actions"
                            data-attr="bi-worksheet-actions"
                        />
                    </LemonMenu>
                    <BIMetricProposalButton tabId={tabId} />
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => saveInsight()}
                        loading={insightLoading}
                        disabledReason={saveDisabledReason}
                        data-attr="bi-save-insight"
                    >
                        Save insight
                    </LemonButton>
                </header>
                {agentUpdateState === 'conflict' && (
                    <LemonBanner type="warning">
                        The assistant changed fields you also edited. Your draft is preserved. Discard changes to use
                        the saved version, or save your draft as a copy.
                    </LemonBanner>
                )}
                {agentUpdateState === 'error' && (
                    <LemonBanner type="warning">
                        Could not refresh assistant changes. Retry before saving.
                        <LemonButton size="small" onClick={() => refreshInsightFromAgent(insight?.id)}>
                            Retry
                        </LemonButton>
                    </LemonBanner>
                )}
                {loadError ? (
                    <LemonBanner type="error">{loadError}</LemonBanner>
                ) : catalogMetricLoading || (insightLoading && !lastRunQuery) ? (
                    <div className="flex flex-1 flex-col items-center justify-center gap-2" role="status">
                        <Spinner />
                        <span>Loading worksheet…</span>
                    </div>
                ) : (
                    <BIEditor tabId={tabId} settingsPanelRef={setSettingsContainer}>
                        {!!worksheet.config.hierarchyDrillPath?.length && (
                            <div
                                className="flex flex-wrap items-center gap-2 px-3 py-1 text-xs"
                                data-attr="bi-hierarchy-path"
                            >
                                <span>
                                    {[
                                        worksheet.config.hierarchyDrillPath[0].previousField.name,
                                        ...worksheet.config.hierarchyDrillPath.map((step) => step.nextField.name),
                                    ].join(' → ')}
                                </span>
                                <LemonButton
                                    size="xsmall"
                                    disabledReason={
                                        !hierarchyParent ? 'The hierarchy or active field has changed' : undefined
                                    }
                                    onClick={() => {
                                        if (hierarchyParent) {
                                            navigateHierarchy(hierarchyParent)
                                        }
                                    }}
                                >
                                    Drill up to{' '}
                                    {hierarchyParent?.config.hierarchyDrillPath?.at(-1)?.nextField.name ??
                                        worksheet.config.hierarchyDrillPath[0].previousField.name}
                                </LemonButton>
                                <span className="text-secondary">
                                    Drill up removes only filters added by this drill.
                                </span>
                            </div>
                        )}
                        {lastRunQuery ? (
                            <Query
                                query={lastRunQuery}
                                setQuery={(query) => {
                                    if (isDataVisualizationNode(query)) {
                                        setVisualization(query)
                                    }
                                }}
                                uniqueKey={`bi-${tabId}`}
                                editMode
                                context={{
                                    insightProps: { dashboardItemId: `new-bi-${tabId}` },
                                    showOpenEditorButton: false,
                                    chartTypeSelectorClassName: worksheet.config.querySnapshot ? undefined : 'hidden',
                                    onEditBIAxis: setEditingAxis,
                                    onDrillBIHierarchy: (next) => navigateHierarchy(next),
                                    biHierarchyDrillDisabledReason: displayedQueryIsCurrent
                                        ? undefined
                                        : 'Run the worksheet before drilling into edited fields',
                                    onKeepBISelection: displayedQueryIsCurrent
                                        ? (records) => {
                                              const config = keepBIScatterRows(worksheet.config, records)
                                              if (config) {
                                                  restoreState({ editorView: BIEditorView.BI, config })
                                                  runAfterChange()
                                              }
                                          }
                                        : undefined,
                                    visualizationSettingsPanel: {
                                        isOpen: activePanel === 'display',
                                        onToggle: () => setActivePanel(activePanel === 'display' ? null : 'display'),
                                        container: settingsContainer,
                                    },
                                }}
                            />
                        ) : (
                            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-4 text-secondary">
                                <span>
                                    {worksheet.config.querySnapshot
                                        ? 'Press Run to see the results of this query snapshot.'
                                        : worksheet.config.source
                                          ? worksheet.config.rows.length ||
                                            worksheet.config.columns.length ||
                                            worksheet.config.values.length
                                              ? 'Press Run to see the results of this worksheet.'
                                              : 'Drag or double-click a field to start. Dimensions define groups; measures calculate a value for each group.'
                                          : 'Select a table and add fields to build your worksheet.'}
                                </span>
                                {generatedQuery && (
                                    <LemonButton
                                        type="primary"
                                        onClick={runQuery}
                                        aria-label="Run worksheet"
                                        data-attr="bi-run-empty-worksheet"
                                    >
                                        Run
                                    </LemonButton>
                                )}
                                {worksheet.config.source &&
                                    !worksheet.config.rows.length &&
                                    !worksheet.config.columns.length &&
                                    !worksheet.config.values.length && (
                                        <LemonButton
                                            type="secondary"
                                            onClick={startSuggestedChart}
                                            disabledReason={dataPaneFieldsLoading ? 'Loading fields' : undefined}
                                            data-attr="bi-start-suggested-chart"
                                        >
                                            {dataPaneFields.dimensions.some((field) =>
                                                ['date', 'datetime'].includes(field.type)
                                            )
                                                ? 'Start with daily row count'
                                                : 'Start with row count'}
                                        </LemonButton>
                                    )}
                            </div>
                        )}
                        {!worksheet.config.querySnapshot && <BIResultSummary tabId={tabId} />}
                    </BIEditor>
                )}
                {editingAxis && (
                    <BIChartAxisModal
                        key={editingAxis}
                        axis={editingAxis}
                        settings={lastRunQuery?.chartSettings ?? {}}
                        onSave={setChartSettings}
                        onClose={() => setEditingAxis(null)}
                    />
                )}
                <LemonModal
                    title="Save as SQL view"
                    isOpen={exportViewOpen}
                    onClose={() => setExportViewOpen(false)}
                    footer={
                        <LemonButton
                            type="primary"
                            loading={exportedViewLoading}
                            disabledReason={!exportViewName.trim() ? 'Enter a view name' : undefined}
                            onClick={exportView}
                        >
                            Create view
                        </LemonButton>
                    }
                >
                    <p>
                        The view saves the generated SQL. Save an insight to keep the worksheet’s shelves and chart
                        settings.
                    </p>
                    <LemonInput
                        value={exportViewName}
                        onChange={setExportViewName}
                        placeholder="View name"
                        aria-label="View name"
                    />
                </LemonModal>
            </div>
        </BindLogic>
    )
}
