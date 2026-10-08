import { BindLogic, useActions, useValues } from 'kea'

import { IconShare } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, Spinner } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { isDataVisualizationNode } from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { BIEditor } from './BIEditor'
import { biSceneLogic } from './biSceneLogic'

export const scene: SceneExport = {
    component: BusinessIntelligenceScene,
    logic: biSceneLogic,
    paramsToProps: ({ params }) => ({
        tabId: `bi-${params.tabId ?? 'default'}`,
    }),
}

export function BusinessIntelligenceScene({ tabId = 'bi-default' }: { tabId?: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const logic = biSceneLogic({ tabId })
    const {
        name,
        lastRunQuery,
        insightLoading,
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
    } = useValues(logic)
    const {
        setName,
        saveInsight,
        discardChanges,
        shareWorksheet,
        setVisualization,
        setExportViewOpen,
        setExportViewName,
        exportView,
        undo,
        redo,
    } = useActions(logic)

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
                <header className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
                    <LemonButton size="small" to={urls.businessIntelligence()}>
                        Worksheets
                    </LemonButton>
                    <LemonInput
                        aria-label="Worksheet name"
                        value={name}
                        onChange={setName}
                        maxLength={400}
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
                        onClick={() => saveInsight({ asCopy: true })}
                        loading={insightLoading}
                        disabledReason={copyDisabledReason}
                        data-attr="bi-save-copy"
                    >
                        Save a copy
                    </LemonButton>
                    <LemonButton
                        size="small"
                        icon={<IconShare />}
                        onClick={shareWorksheet}
                        data-attr="bi-share-worksheet"
                    >
                        Share
                    </LemonButton>
                    <LemonButton
                        size="small"
                        onClick={() => setExportViewOpen(true)}
                        disabledReason={
                            saveDisabledReason ||
                            (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Editor)
                                ? 'You do not have permission to create warehouse views'
                                : undefined)
                        }
                        data-attr="bi-export-sql-view"
                    >
                        Save as SQL view
                    </LemonButton>
                    <LemonButton
                        size="small"
                        onClick={discardChanges}
                        disabledReason={!hasUnsavedChanges ? 'No changes to discard' : undefined}
                        data-attr="bi-discard-changes"
                    >
                        Discard changes
                    </LemonButton>
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
                {loadError ? (
                    <LemonBanner type="error">{loadError}</LemonBanner>
                ) : insightLoading && !lastRunQuery ? (
                    <div className="flex flex-1 items-center justify-center">
                        <Spinner />
                    </div>
                ) : (
                    <BIEditor tabId={tabId}>
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
                                }}
                            />
                        ) : (
                            <div className="flex flex-1 items-center justify-center p-4 text-secondary">
                                {worksheet.config.source
                                    ? 'Press Run to see the results of this worksheet.'
                                    : 'Select a table and add fields to build your worksheet.'}
                            </div>
                        )}
                    </BIEditor>
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
