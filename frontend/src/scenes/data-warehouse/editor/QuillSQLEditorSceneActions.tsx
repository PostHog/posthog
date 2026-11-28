import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconBook, IconChevronDown, IconDownload, IconNotebook, IconWarning, IconX } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Spinner,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { QuillSaveAsMenuItems } from 'products/data_warehouse/frontend/sql_editor/QuillSaveAsMenu'
import type { SaveAsTarget, SaveAsTargetId } from 'products/data_warehouse/frontend/sql_editor/saveAsTargets'
import { sqlEditorLayoutLogic } from 'products/data_warehouse/frontend/sql_editor/workspace/sqlEditorLayoutLogic'

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
    confirmSave: (save: () => void) => void
    needsSaveConfirmation: boolean
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
    confirmSave,
    needsSaveConfirmation,
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
        viewUpdateInProgress,
    } = useValues(sqlEditorLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { convertToNotebook } = useActions(editorSceneLogic)
    const { setInspectorTab } = useActions(sqlEditorLayoutLogic)
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

    // History lives in the side panel here, next to the query it restores into, rather than in a modal.
    const openHistory = (): void => {
        setInspectorTab('history')
        posthog.capture('sql-editor-history-modal-opened', {
            object: editingView ? 'view' : 'insight',
            surface: 'side_panel',
        })
    }

    const historyButton = (dataAttr?: string): JSX.Element => (
        <Button variant="outline" onClick={openHistory} data-attr={dataAttr}>
            <IconBook />
            History
        </Button>
    )

    const discardChangesButton = (
        <Button
            variant="outline"
            onClick={() => discardChanges()}
            disabledReason={
                insightLoading || viewUpdateInProgress || updatingDataWarehouseSavedQuery
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

    const legacySaveAsMenuItemsGroup = (
        <DropdownMenuGroup>
            {legacySaveMenuItems.map((item) => (
                <DropdownMenuItem key={item.action} disabledReason={item.disabledReason} onClick={item.onClick}>
                    {item.label}
                </DropdownMenuItem>
            ))}
        </DropdownMenuGroup>
    )

    // Fewer than 2% of editor users continue in a notebook, so it sits at the foot of the save menu
    // rather than taking a header button next to Run, the scene's only primary action.
    const notebookMenuGroup = (
        <>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>{continueInNotebookMenuItem}</DropdownMenuGroup>
        </>
    )

    const saveAsTargetMenuItems = (
        <>
            <QuillSaveAsMenuItems targets={saveAsTargets} onSelect={onSaveAsTargetSelect} />
            {notebookMenuGroup}
        </>
    )

    const saveOptionsTrigger = (dataAttr?: string): JSX.Element => (
        <DropdownMenuTrigger
            render={
                <Button
                    variant="outline"
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

    const saveWarning = needsSaveConfirmation ? (
        <IconWarning data-attr="sql-editor-save-warning" aria-hidden="true" />
    ) : null

    return (
        <div className="flex flex-wrap items-center gap-2">
            {editingView ? (
                <>
                    {historyButton()}
                    {discardChangesButton}
                    <DropdownMenu onOpenChange={onSaveMenuOpenChange}>
                        <ButtonGroup>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.WarehouseObjects}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={editingView.user_access_level}
                            >
                                <Button
                                    variant="outline"
                                    onClick={onUpdateView}
                                    loading={editingViewLoading && !viewUpdateInProgress}
                                    disabledReason={editingViewDisabledReason}
                                    aria-busy={viewUpdateInProgress || undefined}
                                >
                                    {viewUpdateInProgress ? <Spinner /> : !editingViewLoading && <IconDownload />}
                                    <span>
                                        {viewUpdateInProgress
                                            ? 'Checking downstream views…'
                                            : isMaterializedView
                                              ? 'Update and re-materialize view'
                                              : 'Update view'}
                                    </span>
                                    {saveWarning}
                                </Button>
                            </AccessControlAction>
                            {saveOptionsTrigger()}
                        </ButtonGroup>
                        <DropdownMenuContent
                            align="end"
                            className={saveAsChooserEnabled ? 'w-80' : undefined}
                            data-attr={saveAsChooserEnabled ? 'sql-editor-save-as-dialog' : undefined}
                        >
                            {saveAsChooserEnabled ? (
                                saveAsTargetMenuItems
                            ) : (
                                <>
                                    {legacySaveAsMenuItemsGroup}
                                    {notebookMenuGroup}
                                </>
                            )}
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
                    <DropdownMenu onOpenChange={onSaveMenuOpenChange}>
                        <ButtonGroup>
                            <Button
                                variant="outline"
                                onClick={() => confirmSave(updateInsight)}
                                loading={insightLoading}
                                disabledReason={
                                    saveAsInsightDisabledReason ??
                                    (!updateInsightButtonEnabled ? 'No updates to save' : undefined)
                                }
                            >
                                <span>Update insight</span>
                                {saveWarning}
                            </Button>
                            {saveOptionsTrigger('sql-editor-save-options-button')}
                        </ButtonGroup>
                        <DropdownMenuContent
                            align="end"
                            className={saveAsChooserEnabled ? 'w-80' : undefined}
                            data-attr={saveAsChooserEnabled ? 'sql-editor-save-as-dialog' : undefined}
                        >
                            {saveAsChooserEnabled ? (
                                saveAsTargetMenuItems
                            ) : (
                                <>
                                    {legacySaveAsMenuItemsGroup}
                                    {notebookMenuGroup}
                                </>
                            )}
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
                    <DropdownMenu onOpenChange={onSaveMenuOpenChange}>
                        <ButtonGroup>
                            <Button
                                variant="outline"
                                onClick={() => confirmSave(updateEditingMetric)}
                                loading={metricUpdating}
                                disabledReason={saveAsDisabledReason}
                                data-attr="sql-editor-update-metric"
                            >
                                <span>Update metric</span>
                                {saveWarning}
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
                            {!saveAsChooserEnabled && notebookMenuGroup}
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
                    {saveAsChooserEnabled ? (
                        <DropdownMenu onOpenChange={onSaveMenuOpenChange}>
                            <DropdownMenuTrigger
                                render={<Button variant="outline" data-attr="sql-editor-save-options-button" />}
                            >
                                <span>Save as</span>
                                {saveWarning}
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
                                    variant="outline"
                                    onClick={onPrimarySaveClick}
                                    disabledReason={primarySaveDisabledReason}
                                >
                                    <span>{saveAsMenuItems.primary.label}</span>
                                    {saveWarning}
                                </Button>
                                {saveOptionsTrigger('sql-editor-save-options-button')}
                            </ButtonGroup>
                            <DropdownMenuContent align="end">
                                <DropdownMenuGroup>
                                    {secondarySaveMenuItems.map((item) => (
                                        <DropdownMenuItem
                                            key={item.action}
                                            disabledReason={item.disabledReason}
                                            onClick={item.onClick}
                                        >
                                            {item.label}
                                        </DropdownMenuItem>
                                    ))}
                                </DropdownMenuGroup>
                                {notebookMenuGroup}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                </>
            )}
        </div>
    )
}
