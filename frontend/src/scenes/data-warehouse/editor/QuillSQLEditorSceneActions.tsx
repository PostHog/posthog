import { useActions, useValues } from 'kea'

import { IconBook, IconChevronDown, IconDownload, IconNotebook, IconX } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { QuillSaveAsMenuItems } from 'products/data_warehouse/frontend/sql_editor/QuillSaveAsMenu'
import type { SaveAsTarget, SaveAsTargetId } from 'products/data_warehouse/frontend/sql_editor/saveAsTargets'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { SaveAsMenuItem, editorSceneLogic } from './editorSceneLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

export interface QuillSQLEditorSecondarySaveMenuItem extends SaveAsMenuItem {
    onClick: () => void
    disabledReason: string | null | undefined
}

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
    secondarySaveMenuItems: QuillSQLEditorSecondarySaveMenuItem[]
    legacySaveMenuItems: QuillSQLEditorSecondarySaveMenuItem[]
    saveAsTargets: SaveAsTarget[]
    onSaveAsTargetSelect: (target: SaveAsTargetId) => void
    onSaveAsMenuOpen: () => void
    onPrimarySaveClick: () => void
    primarySaveDisabledReason: string | null | undefined
    saveAsChooserEnabled: boolean
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
    secondarySaveMenuItems,
    legacySaveMenuItems,
    saveAsTargets,
    onSaveAsTargetSelect,
    onSaveAsMenuOpen,
    onPrimarySaveClick,
    primarySaveDisabledReason,
    saveAsChooserEnabled,
}: QuillSQLEditorSceneActionsProps): JSX.Element {
    const { updateInsightButtonEnabled, saveAsMenuItems, notebooksLoading } = useValues(editorSceneLogic)
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
        if (open && saveAsChooserEnabled) {
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

    const continueInNotebookMenuItem = (
        <DropdownMenuItem
            onClick={() => convertToNotebook()}
            disabledReason={notebooksLoading ? 'Creating notebook...' : continueInNotebookDisabledReason}
            data-attr="sql-editor-continue-in-notebook-button"
        >
            <IconNotebook />
            Continue in a notebook
        </DropdownMenuItem>
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

    const legacySaveAsMenuItemsGroup = (
        <DropdownMenuGroup>
            {continueInNotebookMenuItem}
            {legacySaveMenuItems.map((item) => (
                <DropdownMenuItem key={item.action} disabledReason={item.disabledReason} onClick={item.onClick}>
                    {item.label}
                </DropdownMenuItem>
            ))}
        </DropdownMenuGroup>
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
                    {saveAsChooserEnabled && continueInNotebookButton}
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
                        <DropdownMenuContent
                            align="end"
                            className={saveAsChooserEnabled ? 'w-80' : undefined}
                            data-attr={saveAsChooserEnabled ? 'sql-editor-save-as-dialog' : undefined}
                        >
                            {saveAsChooserEnabled ? saveAsTargetMenuItems : legacySaveAsMenuItemsGroup}
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
                    {saveAsChooserEnabled && continueInNotebookButton}
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
                        <DropdownMenuContent
                            align="end"
                            className={saveAsChooserEnabled ? 'w-80' : undefined}
                            data-attr={saveAsChooserEnabled ? 'sql-editor-save-as-dialog' : undefined}
                        >
                            {saveAsChooserEnabled ? saveAsTargetMenuItems : legacySaveAsMenuItemsGroup}
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
                    {saveAsChooserEnabled && continueInNotebookButton}
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
                        <DropdownMenuContent
                            align="end"
                            className={saveAsChooserEnabled ? 'w-80' : undefined}
                            data-attr={saveAsChooserEnabled ? 'sql-editor-save-as-dialog' : undefined}
                        >
                            {saveAsChooserEnabled
                                ? saveAsTargetMenuItems
                                : secondarySaveMenuItems.map((item) => (
                                      <DropdownMenuItem
                                          key={item.action}
                                          disabledReason={item.disabledReason}
                                          onClick={item.onClick}
                                      >
                                          {item.label}
                                      </DropdownMenuItem>
                                  ))}
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
                    {(saveAsChooserEnabled || saveAsMenuItems.primary.action === 'insight') && continueInNotebookButton}
                    {saveAsChooserEnabled ? (
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
                    ) : (
                        <DropdownMenu>
                            <ButtonGroup>
                                <Button
                                    variant="primary"
                                    onClick={onPrimarySaveClick}
                                    disabledReason={primarySaveDisabledReason}
                                >
                                    {saveAsMenuItems.primary.label}
                                </Button>
                                {saveOptionsTrigger('sql-editor-save-options-button')}
                            </ButtonGroup>
                            <DropdownMenuContent align="end">
                                {secondarySaveMenuItems.map((item) => (
                                    <DropdownMenuItem
                                        key={item.action}
                                        disabledReason={item.disabledReason}
                                        onClick={item.onClick}
                                    >
                                        {item.label}
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                </>
            )}
        </div>
    )
}
