import { useActions, useValues } from 'kea'

import { IconBook, IconChevronDown, IconDownload, IconNotebook, IconX } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { SaveAsMenuItem, editorSceneLogic } from './editorSceneLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

export interface QuillSQLEditorSecondarySaveMenuItem extends SaveAsMenuItem {
    onClick: () => void
    disabledReason: string | null | undefined
}

export interface QuillSQLEditorSceneActionsProps {
    isMaterializedView: boolean
    closeObjectTooltip: string
    editingViewDisabledReason: string | undefined
    editingViewLoading: boolean
    onUpdateView: () => void
    saveAsInsightDisabledReason: string | undefined
    saveAsDisabledReason: string | undefined
    continueInNotebookAccessDisabledReason: string | null
    secondarySaveMenuItems: QuillSQLEditorSecondarySaveMenuItem[]
    legacySaveMenuItems: QuillSQLEditorSecondarySaveMenuItem[]
    onPrimarySaveClick: () => void
    primarySaveDisabledReason: string | null | undefined
    saveAsChooserEnabled: boolean
}

export function QuillSQLEditorSceneActions({
    isMaterializedView,
    closeObjectTooltip,
    editingViewDisabledReason,
    editingViewLoading,
    onUpdateView,
    saveAsInsightDisabledReason,
    saveAsDisabledReason,
    continueInNotebookAccessDisabledReason,
    secondarySaveMenuItems,
    legacySaveMenuItems,
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
    const { convertToNotebook, openHistoryModal, openSaveAsModal } = useActions(editorSceneLogic)
    const { updateInsight, closeEditingObject, updateEditingMetric, setEditingMetricName, discardChanges } =
        useActions(sqlEditorLogic)

    const continueInNotebookDisabledReason = queryInput?.trim()
        ? continueInNotebookAccessDisabledReason
        : 'Write a SQL query before continuing'

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

    const saveAsMenuItem = (
        <DropdownMenuItem onClick={() => openSaveAsModal()} data-attr="sql-editor-save-as-button">
            Save as...
        </DropdownMenuItem>
    )

    const saveAsMenuItemsGroup = (
        <DropdownMenuGroup>
            {continueInNotebookMenuItem}
            {saveAsChooserEnabled
                ? saveAsMenuItem
                : legacySaveMenuItems.map((item) => (
                      <DropdownMenuItem key={item.action} disabledReason={item.disabledReason} onClick={item.onClick}>
                          {item.label}
                      </DropdownMenuItem>
                  ))}
        </DropdownMenuGroup>
    )

    const saveAsMenuContent = (
        <DropdownMenuContent align="end">
            {saveAsChooserEnabled ? (
                <DropdownMenuGroup>{saveAsMenuItem}</DropdownMenuGroup>
            ) : (
                secondarySaveMenuItems.map((item) => (
                    <DropdownMenuItem key={item.action} disabledReason={item.disabledReason} onClick={item.onClick}>
                        {item.label}
                    </DropdownMenuItem>
                ))
            )}
        </DropdownMenuContent>
    )

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
                    <DropdownMenu>
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
                        <DropdownMenuContent align="end">{saveAsMenuItemsGroup}</DropdownMenuContent>
                    </DropdownMenu>
                    <Button
                        variant="default"
                        size="icon"
                        onClick={() => closeEditingObject()}
                        aria-label="close"
                        tooltip={closeObjectTooltip}
                    >
                        <IconX />
                    </Button>
                </>
            ) : editingInsight ? (
                <>
                    {historyButton('sql-editor-insight-history-button')}
                    {discardChangesButton}
                    <DropdownMenu>
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
                        <DropdownMenuContent align="end">
                            {saveAsMenuItemsGroup}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                                onClick={() => closeEditingObject()}
                                data-attr="sql-editor-reset-view"
                                title={closeObjectTooltip}
                            >
                                Reset view
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </>
            ) : editingMetricName ? (
                <>
                    <DropdownMenu>
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
                        {saveAsMenuContent}
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
                    {saveAsMenuItems.primary.action === 'insight' && (
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
                    )}
                    {saveAsChooserEnabled ? (
                        <Button
                            variant="primary"
                            onClick={() => openSaveAsModal()}
                            disabledReason={saveAsInsightDisabledReason}
                            data-attr="sql-editor-save-options-button"
                        >
                            Save as...
                        </Button>
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
                            {saveAsMenuContent}
                        </DropdownMenu>
                    )}
                </>
            )}
        </div>
    )
}
