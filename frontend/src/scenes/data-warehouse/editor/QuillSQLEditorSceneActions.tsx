import { useActions, useValues } from 'kea'

import { IconBook, IconChevronDown, IconDownload, IconNotebook, IconX } from '@posthog/icons'
import { Button, ButtonGroup, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { QuillSaveAsMenuItems } from 'products/data_warehouse/frontend/sql_editor/QuillSaveAsMenu'
import type { SaveAsTarget, SaveAsTargetId } from 'products/data_warehouse/frontend/sql_editor/saveAsTargets'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { editorSceneLogic } from './editorSceneLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

export interface QuillSQLEditorSceneActionsProps {
    isMaterializedView: boolean
    closeObjectLabel: string
    closeObjectTooltip: string
    editingViewDisabledReason: string | undefined
    editingViewLoading: boolean
    onUpdateView: () => void
    saveAsInsightDisabledReason: string | undefined
    saveAsDisabledReason: string | undefined
    continueInNotebookAccessDisabledReason: string | null
    saveAsTargets: SaveAsTarget[]
    onSaveAsTargetSelect: (target: SaveAsTargetId) => void
    onSaveAsMenuOpen: () => void
}

export function QuillSQLEditorSceneActions({
    isMaterializedView,
    closeObjectLabel,
    closeObjectTooltip,
    editingViewDisabledReason,
    editingViewLoading,
    onUpdateView,
    saveAsInsightDisabledReason,
    saveAsDisabledReason,
    continueInNotebookAccessDisabledReason,
    saveAsTargets,
    onSaveAsTargetSelect,
    onSaveAsMenuOpen,
}: QuillSQLEditorSceneActionsProps): JSX.Element {
    const { updateInsightButtonEnabled, notebooksLoading } = useValues(editorSceneLogic)
    const {
        queryInput,
        editingView,
        editingInsight,
        insightLoading,
        hasEditorChanges,
        editingMetricName,
        metricUpdating,
    } = useValues(sqlEditorLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { convertToNotebook, openHistoryModal } = useActions(editorSceneLogic)
    const { updateInsight, closeEditingObject, updateEditingMetric, setEditingMetricName, discardChanges } =
        useActions(sqlEditorLogic)

    const continueInNotebookDisabledReason = queryInput?.trim()
        ? continueInNotebookAccessDisabledReason
        : 'Write a SQL query before continuing'

    const onSaveMenuOpenChange = (open: boolean): void => {
        if (open) {
            onSaveAsMenuOpen()
        }
    }

    const historyButton = (dataAttr?: string): JSX.Element => (
        <Button variant="outline" onClick={() => openHistoryModal()} data-attr={dataAttr}>
            <IconBook />
            History
        </Button>
    )

    const discardChangesButton = (
        <Button
            variant="outline"
            onClick={() => discardChanges()}
            disabledReason={
                insightLoading || updatingDataWarehouseSavedQuery
                    ? 'Wait for the current operation to finish'
                    : !hasEditorChanges
                      ? 'No changes to discard'
                      : undefined
            }
            data-attr="sql-editor-discard-changes"
        >
            Discard changes
        </Button>
    )

    const continueInNotebookButton = (
        <Button
            variant="outline"
            onClick={() => convertToNotebook()}
            loading={notebooksLoading}
            disabledReason={continueInNotebookDisabledReason}
            data-attr="sql-editor-continue-in-notebook-button"
        >
            <IconNotebook />
            Continue in a notebook
        </Button>
    )

    const saveAsTargetMenuItems = <QuillSaveAsMenuItems targets={saveAsTargets} onSelect={onSaveAsTargetSelect} />

    const saveOptionsTrigger = (dataAttr?: string): JSX.Element => (
        <DropdownMenuTrigger
            render={
                <Button
                    variant="primary"
                    size="icon"
                    aria-label="More save options"
                    tooltip="More save options"
                    data-attr={dataAttr}
                />
            }
        >
            <IconChevronDown />
        </DropdownMenuTrigger>
    )

    return (
        <div className="flex flex-wrap items-center gap-2">
            {editingView ? (
                <>
                    {historyButton()}
                    {discardChangesButton}
                    {continueInNotebookButton}
                    <DropdownMenu onOpenChange={onSaveMenuOpenChange}>
                        <ButtonGroup>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.WarehouseObjects}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={editingView.user_access_level}
                            >
                                <Button
                                    variant="primary"
                                    onClick={onUpdateView}
                                    loading={editingViewLoading}
                                    disabledReason={editingViewDisabledReason}
                                >
                                    {!editingViewLoading && <IconDownload />}
                                    {isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
                                </Button>
                            </AccessControlAction>
                            {saveOptionsTrigger()}
                        </ButtonGroup>
                        <DropdownMenuContent align="end" className="w-80" data-attr="sql-editor-save-as-dialog">
                            {saveAsTargetMenuItems}
                        </DropdownMenuContent>
                    </DropdownMenu>
                    <Button
                        variant="default"
                        size="icon"
                        onClick={() => closeEditingObject()}
                        aria-label={closeObjectLabel}
                        tooltip={closeObjectTooltip}
                    >
                        <IconX />
                    </Button>
                </>
            ) : editingInsight ? (
                <>
                    {historyButton('sql-editor-insight-history-button')}
                    {discardChangesButton}
                    {continueInNotebookButton}
                    <DropdownMenu onOpenChange={onSaveMenuOpenChange}>
                        <ButtonGroup>
                            <Button
                                variant="primary"
                                onClick={() => updateInsight()}
                                loading={insightLoading}
                                disabledReason={
                                    saveAsInsightDisabledReason ??
                                    (!updateInsightButtonEnabled ? 'No updates to save' : undefined)
                                }
                            >
                                Update insight
                            </Button>
                            {saveOptionsTrigger('sql-editor-save-options-button')}
                        </ButtonGroup>
                        <DropdownMenuContent align="end" className="w-80" data-attr="sql-editor-save-as-dialog">
                            {saveAsTargetMenuItems}
                        </DropdownMenuContent>
                    </DropdownMenu>
                    <Button
                        variant="default"
                        size="icon"
                        onClick={() => closeEditingObject()}
                        aria-label={closeObjectLabel}
                        tooltip={closeObjectTooltip}
                        data-attr="sql-editor-reset-view"
                    >
                        <IconX />
                    </Button>
                </>
            ) : editingMetricName ? (
                <>
                    {continueInNotebookButton}
                    <DropdownMenu onOpenChange={onSaveMenuOpenChange}>
                        <ButtonGroup>
                            <Button
                                variant="primary"
                                onClick={() => updateEditingMetric()}
                                loading={metricUpdating}
                                disabledReason={saveAsDisabledReason}
                                data-attr="sql-editor-update-metric"
                            >
                                Update metric
                            </Button>
                            {saveOptionsTrigger()}
                        </ButtonGroup>
                        <DropdownMenuContent align="end" className="w-80" data-attr="sql-editor-save-as-dialog">
                            {saveAsTargetMenuItems}
                        </DropdownMenuContent>
                    </DropdownMenu>
                    <Button
                        variant="default"
                        size="icon"
                        onClick={() => setEditingMetricName(null)}
                        aria-label="Stop editing metric"
                        tooltip="Stop editing this metric and start a new query"
                    >
                        <IconX />
                    </Button>
                </>
            ) : (
                <>
                    {continueInNotebookButton}

                    <DropdownMenu onOpenChange={onSaveMenuOpenChange}>
                        <DropdownMenuTrigger
                            render={<Button variant="primary" data-attr="sql-editor-save-options-button" />}
                        >
                            Save as
                            <IconChevronDown />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-80" data-attr="sql-editor-save-as-dialog">
                            {saveAsTargetMenuItems}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </>
            )}
        </div>
    )
}
