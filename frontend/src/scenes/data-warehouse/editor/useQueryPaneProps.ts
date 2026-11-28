import { Monaco } from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import type { editor as importedEditor } from 'monaco-editor'
import type { ComponentProps } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { registerHogQLFormattingProvider } from 'lib/monaco/hogQLFormattingProvider'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { sqlEditorVimLogic } from 'products/data_warehouse/frontend/shared/logics/sqlEditorVimLogic'
import { registerSqlTableHover } from 'products/data_warehouse/frontend/shared/sqlTableHover'

import { QueryPane } from './QueryPane'
import { sqlEditorLogic, tabModelPath } from './sqlEditorLogic'

export interface QueryPaneHostOptions {
    tabId: string
    codeEditorKey: string
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
    onRunQuery?: () => void
    runQueryLoading?: boolean
    autoFocusQueryPane?: boolean
    captureQueryTelemetry?: boolean
}

export function useQueryPaneProps({
    tabId,
    codeEditorKey,
    onSetMonacoAndEditor,
    onRunQuery,
    runQueryLoading,
    autoFocusQueryPane,
    captureQueryTelemetry,
}: QueryPaneHostOptions): Omit<ComponentProps<typeof QueryPane>, 'constrainHeight'> {
    const logic = sqlEditorLogic({ tabId, captureQueryTelemetry })
    const {
        queryInput,
        sourceQuery,
        originalQueryInput,
        suggestedQueryInput,
        activeQueryText,
        activeQueryOffset,
        sendRawQueryEnabled,
        placeholderValues,
    } = useValues(logic)
    const { setQueryInput, runQuery, runSubquery, setError, setMetadata, setMetadataLoading, fixIndexUsageWithAI } =
        useActions(logic)
    const vimModeFeatureEnabled = useFeatureFlag('SQL_EDITOR_VIM_MODE')
    const { vimModeEnabled, vimrc } = useValues(sqlEditorVimLogic)

    return {
        originalValue: originalQueryInput ?? undefined,
        queryInput: (suggestedQueryInput || queryInput) ?? '',
        sourceQuery: sourceQuery.source,
        promptError: null,
        onRun: runQuery,
        editorVimModeEnabled: vimModeFeatureEnabled && vimModeEnabled,
        editorVimrc: vimrc,
        codeEditorProps: {
            ...(sendRawQueryEnabled ? { language: 'sql' } : {}),
            queryKey: codeEditorKey,
            autoFocus: autoFocusQueryPane ?? true,
            // Bind the editor to the tab's persistent Monaco model and keep it
            // alive across the diff <-> editor swap, so undo history survives an
            // accepted AI suggestion. Shares the URI with the model createTab makes.
            path: tabModelPath(tabId),
            keepCurrentModel: true,
            metadataQuery: activeQueryText ?? undefined,
            metadataQueryOffset: activeQueryOffset,
            // Set here rather than only where the tab's Monaco model is created: an editor
            // that mounts against an existing model never runs that path, and would then
            // ask for metadata without the index report.
            indexUsage: true,
            // Lets error checking resolve the host's placeholders instead of flagging them
            globals: placeholderValues ?? undefined,
            captureQueryTelemetry,
            onFixWithAI: (prompt) => fixIndexUsageWithAI(prompt),
            onChange: (v) => {
                setQueryInput(v ?? '')
            },
            onMount: (editor, monaco) => {
                registerHogQLFormattingProvider(monaco)
                registerSqlTableHover(monaco, editor, () => {
                    const schema = databaseTableListLogic.findMounted()
                    return schema?.values.connectionId === (logic.values.selectedSchemaConnectionId ?? null)
                        ? schema.values.allTablesMap
                        : {}
                })
                onSetMonacoAndEditor(monaco, editor)
            },
            onPressCmdEnter: (value, selectionType) => {
                if (onRunQuery) {
                    if (!runQueryLoading) {
                        onRunQuery()
                    }
                    return
                }
                if (value && selectionType === 'selection') {
                    runQuery(value)
                } else {
                    runQuery()
                }
            },
            onPressCmdShiftEnter: onRunQuery
                ? () => {
                      if (!runQueryLoading) {
                          onRunQuery()
                      }
                  }
                : runSubquery,
            onError: (error) => {
                setError(error)
            },
            onMetadata: (metadata) => {
                setMetadata(metadata)
            },
            onMetadataLoading: (loading) => {
                setMetadataLoading(loading)
            },
        },
    }
}
